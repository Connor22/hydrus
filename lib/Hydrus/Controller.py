### IMPORTS ###
import collections, os, random, sys, threading, time, traceback, requests, gc

from lib.Hydrus import Constants as HC, Data, DB, Exceptions, Globals as HG, NATPunch, Paths, PubSub, Threading, Networking, Serialisable, VideoHandling

from lib.Server import DB

from lib.Client import ClientAPI, Caches, ClientData, Daemons, Defaults, Options, ClientPaths, ClientThreading, Constants as CC, ClientDB
from lib.Client.Networking import ClientNetworking, NetworkingBandwidth, NetworkingDomain, NetworkingLogin, NetworkingSessions

from lib.ClientGUI import ClientGUI, TopLevelWindows, Common, Menus
from lib.ClientGUI.Dialogs import Dialogs
from lib.ClientGUI.ScrolledPanels import ScrolledPanelsManagement

import hashlib, gc, psutil, threading, time, traceback

if not HG.twisted_is_broke:   
    from twisted.internet import reactor, defer, ssl

### CODE ###
class HydrusController( object ):  
    def __init__( self, db_dir ):
        HG.controller = self
        
        self._name = 'hydrus'
        self.db_dir = db_dir
        self.db = None
        
        self._model_shutdown = False
        self._view_shutdown = False
        
        self._pubsub = HydrusPubSub.HydrusPubSub( self )
        self._daemons = []
        self._daemon_jobs = {}
        self._caches = {}
        self._managers = {}
        
        self._fast_job_scheduler = None
        self._slow_job_scheduler = None
        
        self._thread_slots = {}
        self._thread_slots[ 'misc' ] = ( 0, 10 )
        self._thread_slot_lock = threading.Lock()
        
        self._call_to_threads = []
        self._long_running_call_to_threads = []
        
        self._thread_pool_busy_status_text = ''
        self._thread_pool_busy_status_text_new_check_time = 0
        
        self._call_to_thread_lock = threading.Lock()
        
        self._timestamps = collections.defaultdict( lambda: 0 )
        self._timestamps[ 'boot' ] = HydrusData.GetNow()
        self._timestamps[ 'last_sleep_check' ] = HydrusData.GetNow()
        
        self._sleep_lock = threading.Lock()
        self._just_woke_from_sleep = False
        
        self._system_busy = False
        
        self.CallToThreadLongRunning( self.DAEMONPubSub )
        
    
    def _GetCallToThread( self ):
        with self._call_to_thread_lock:
            for call_to_thread in self._call_to_threads:
                if not call_to_thread.CurrentlyWorking():
                    return call_to_thread
                    
                
            # all the threads in the pool are currently busy
            
            calling_from_the_thread_pool = threading.current_thread() in self._call_to_threads
            
            if calling_from_the_thread_pool or len( self._call_to_threads ) < 200:
                call_to_thread = HydrusThreading.THREADCallToThread( self, 'CallToThread' )
                
                self._call_to_threads.append( call_to_thread )
                
                call_to_thread.start()
                
            else:
                call_to_thread = random.choice( self._call_to_threads )
                
            
            return call_to_thread
            
        
    
    def _GetCallToThreadLongRunning( self ):
        with self._call_to_thread_lock:
            for call_to_thread in self._long_running_call_to_threads:
                if not call_to_thread.CurrentlyWorking():
                    return call_to_thread
                    
            call_to_thread = HydrusThreading.THREADCallToThread( self, 'CallToThreadLongRunning' )
            
            self._long_running_call_to_threads.append( call_to_thread )
            
            call_to_thread.start()
            
            return call_to_thread
            
    
    def _GetAppropriateJobScheduler( self, time_delta ):
        if time_delta <= 1.0:
            return self._fast_job_scheduler
            
        else:
            return self._slow_job_scheduler
            
        
    
    def _GetUPnPServices( self ):
        return []
        
    
    def _InitDB( self ):
        raise NotImplementedError()
        
    
    def _InitTempDir( self ):
        self.temp_dir = HydrusPaths.GetTempDir()
        
    
    def _MaintainCallToThreads( self ):
        # we don't really want to hang on to threads that are done as event.wait() has a bit of idle cpu
        # so, any that are in the pools that aren't doing anything can be killed and sent to garbage
        
        with self._call_to_thread_lock:
            def filter_call_to_threads( t ):
                if t.CurrentlyWorking():
                    return True
                    
                else:
                    t.shutdown()
                    
                    return False
                    
                
            
            self._call_to_threads = list(filter( filter_call_to_threads, self._call_to_threads ))
            
            self._long_running_call_to_threads = list(filter( filter_call_to_threads, self._long_running_call_to_threads ))
            
    
    def _Read( self, action, *args, **kwargs ):
        result = self.db.Read( action, *args, **kwargs )
        
        return result
        
    
    def _ReportShutdownDaemonsStatus( self ):
        pass
        
    
    def _ShutdownDaemons( self ):
        for job in self._daemon_jobs.values():
            job.Cancel()
            
        
        self._daemon_jobs = {}
        
        for daemon in self._daemons:
            daemon.shutdown()
            
        
        while True in ( daemon.is_alive() for daemon in self._daemons ):
            self._ReportShutdownDaemonsStatus()
            
            time.sleep( 0.1 )
            
        
        self._daemons = []
        
    
    def _Write( self, action, synchronous, *args, **kwargs ):
        result = self.db.Write( action, synchronous, *args, **kwargs )
        
        return result
        
    
    def pub( self, topic, *args, **kwargs ):
        if self._model_shutdown:
            self._pubsub.pubimmediate( topic, *args, **kwargs )
            
        else:
            self._pubsub.pub( topic, *args, **kwargs )
            
        
    
    def pubimmediate( self, topic, *args, **kwargs ):
        self._pubsub.pubimmediate( topic, *args, **kwargs )
        
    
    def sub( self, object, method_name, topic ):
        self._pubsub.sub( object, method_name, topic )
        
    
    def AcquireThreadSlot( self, thread_type ):
        with self._thread_slot_lock:
            if thread_type not in self._thread_slots:
                return True # assume no max if no max set
            
            ( current_threads, max_threads ) = self._thread_slots[ thread_type ]
            
            if current_threads < max_threads:
                self._thread_slots[ thread_type ] = ( current_threads + 1, max_threads )
                
                return True
                
            else:
                return False
                
            
        
    
    def CallLater( self, initial_delay, func, *args, **kwargs ):
        job_scheduler = self._GetAppropriateJobScheduler( initial_delay )
        
        call = HydrusData.Call( func, *args, **kwargs )
        
        job = HydrusThreading.SchedulableJob( self, job_scheduler, initial_delay, call )
        
        job_scheduler.AddJob( job )
        
        return job
        
    
    def CallRepeating( self, initial_delay, period, func, *args, **kwargs ):
        job_scheduler = self._GetAppropriateJobScheduler( period )
        
        call = HydrusData.Call( func, *args, **kwargs )
        
        job = HydrusThreading.RepeatingJob( self, job_scheduler, initial_delay, period, call )
        
        job_scheduler.AddJob( job )
        
        return job
        
    
    def CallToThread( self, callable, *args, **kwargs ):
        if HG.callto_report_mode:
            what_to_report = [ callable ]
            
            if len( args ) > 0:
                what_to_report.append( args )
                
            
            if len( kwargs ) > 0:
                what_to_report.append( kwargs )
                
            
            HydrusData.ShowText( tuple( what_to_report ) )
            
        
        call_to_thread = self._GetCallToThread()
        
        call_to_thread.put( callable, *args, **kwargs )
        
    
    def CallToThreadLongRunning( self, callable, *args, **kwargs ):
        if HG.callto_report_mode:
            what_to_report = [ callable ]
            
            if len( args ) > 0:
                what_to_report.append( args )
                
            
            if len( kwargs ) > 0:
                what_to_report.append( kwargs )
                
            
            HydrusData.ShowText( tuple( what_to_report ) )
            
        
        call_to_thread = self._GetCallToThreadLongRunning()
        
        call_to_thread.put( callable, *args, **kwargs )
        
    
    def ClearCaches( self ):
        for cache in list(self._caches.values()): cache.Clear()
        
    
    def CurrentlyIdle( self ):
        return True
        
    
    def CurrentlyPubSubbing( self ):
        return self._pubsub.WorkToDo() or self._pubsub.DoingWork()
        
    
    def DBCurrentlyDoingJob( self ):
        if self.db is None:
            return False
            
        else:
            return self.db.CurrentlyDoingJob()
            
        
    
    def DebugShowScheduledJobs( self ):
        summary = self._fast_job_scheduler.GetPrettyJobSummary()
        
        HydrusData.ShowText( 'fast scheduler:' )
        HydrusData.ShowText( summary )
        
        summary = self._slow_job_scheduler.GetPrettyJobSummary()
        
        HydrusData.ShowText( 'slow scheduler:' )
        HydrusData.ShowText( summary )
        
    
    def GetBootTime( self ):
        return self._timestamps[ 'boot' ]
        
    
    def GetDBDir( self ):
        return self.db_dir
        
    
    def GetDBStatus( self ):
        return self.db.GetStatus()
        
    
    def GetCache( self, name ):
        return self._caches[ name ]
        
    
    def GetManager( self, name ):
        return self._managers[ name ]
        
    
    def GetThreadPoolBusyStatus( self ):
        if HydrusData.TimeHasPassed( self._thread_pool_busy_status_text_new_check_time ):
            with self._call_to_thread_lock:
                num_threads = sum( ( 1 for t in self._call_to_threads if t.CurrentlyWorking() ) )
                
            
            if num_threads < 4:
                self._thread_pool_busy_status_text = ''
                
            elif num_threads < 10:
                self._thread_pool_busy_status_text = 'working'
                
            elif num_threads < 20:
                self._thread_pool_busy_status_text = 'busy'
                
            else:
                self._thread_pool_busy_status_text = 'very busy!'
                
            
            self._thread_pool_busy_status_text_new_check_time = HydrusData.GetNow() + 10
            
        
        return self._thread_pool_busy_status_text
        
    
    def GetThreadsSnapshot( self ):
        threads = []
        
        threads.extend( self._daemons )
        threads.extend( self._call_to_threads )
        threads.extend( self._long_running_call_to_threads )
        
        threads.append( self._slow_job_scheduler )
        threads.append( self._fast_job_scheduler )
        
        return threads
        
    
    def GoodTimeToDoBackgroundWork( self ):
        return self.CurrentlyIdle() and not ( self.JustWokeFromSleep() or self.SystemBusy() )
        
    
    def GoodTimeToDoForegroundWork( self ):
        return not self.JustWokeFromSleep()
        
    
    def JustWokeFromSleep( self ):
        self.SleepCheck()
        
        return self._just_woke_from_sleep
        
    
    def InitModel( self ):
        try:
            self._InitTempDir()
            
        except:
            HydrusData.Print( 'Failed to initialise temp folder.' )
            
        
        self._fast_job_scheduler = HydrusThreading.JobScheduler( self )
        self._slow_job_scheduler = HydrusThreading.JobScheduler( self )
        
        self._fast_job_scheduler.start()
        self._slow_job_scheduler.start()
        
        self.db = self._InitDB()
        
    
    def InitView( self ):
        job = self.CallRepeating( 60.0, 300.0, self.MaintainDB )
        
        job.ShouldDelayOnWakeup( True )
        
        self._daemon_jobs[ 'maintain_db' ] = job
        
        job = self.CallRepeating( 10.0, 120.0, self.SleepCheck )
        
        self._daemon_jobs[ 'sleep_check' ] = job
        
        job = self.CallRepeating( 10.0, 60.0, self.MaintainMemoryFast )
        
        self._daemon_jobs[ 'maintain_memory_fast' ] = job
        
        job = self.CallRepeating( 10.0, 300.0, self.MaintainMemorySlow )
        
        self._daemon_jobs[ 'maintain_memory_slow' ] = job
        
        upnp_services = self._GetUPnPServices()
        
        self.services_upnp_manager = HydrusNATPunch.ServicesUPnPManager( upnp_services )
        
        job = self.CallRepeating( 10.0, 43200.0, self.services_upnp_manager.RefreshUPnP )
        
        self._daemon_jobs[ 'services_upnp' ] = job
        
    
    def IsFirstStart( self ):
        if self.db is None:
            return False
            
        else:
            return self.db.IsFirstStart()
            
        
    
    def MaintainDB( self, stop_time = None ):
        pass
        
    
    def MaintainMemoryFast( self ):
        self.pub( 'memory_maintenance_pulse' )
        
        self._fast_job_scheduler.ClearOutDead()
        self._slow_job_scheduler.ClearOutDead()
        
    
    def MaintainMemorySlow( self ):
        sys.stdout.flush()
        sys.stderr.flush()
        
        gc.collect()
        
        #
        del gc.garbage[:]
        
        gc.collect()
        
        HydrusPaths.CleanUpOldTempPaths()
        
        self._MaintainCallToThreads()
        
    
    def ModelIsShutdown( self ):
        return self._model_shutdown
        
    
    def PrintProfile( self, summary, profile_text ):
        boot_pretty_timestamp = time.strftime( '%Y-%m-%d %H-%M-%S', time.localtime( self._timestamps[ 'boot' ] ) )
        
        profile_log_filename = self._name + ' profile - ' + boot_pretty_timestamp + '.log'
        
        profile_log_path = os.path.join( self.db_dir, profile_log_filename )
        
        with open( profile_log_path, 'a', encoding = 'utf-8' ) as f:
            prefix = time.strftime( '%Y/%m/%d %H:%M:%S: ' )
            
            f.write( prefix + summary )
            f.write( os.linesep * 2 )
            f.write( profile_text )
            
        
    
    def ProcessPubSub( self ):
        self._pubsub.Process()
        
    
    def Read( self, action, *args, **kwargs ):
        return self._Read( action, *args, **kwargs )
        
    
    def ReleaseThreadSlot( self, thread_type ):
        with self._thread_slot_lock:
            if thread_type not in self._thread_slots:
                return
                
            
            ( current_threads, max_threads ) = self._thread_slots[ thread_type ]
            
            self._thread_slots[ thread_type ] = ( current_threads - 1, max_threads )
            
        
    
    def ReportDataUsed( self, num_bytes ):
        pass
        
    
    def ReportRequestUsed( self ):
        pass
        
    
    def ResetIdleTimer( self ):
        self._timestamps[ 'last_user_action' ] = HydrusData.GetNow()
        
    
    def ShutdownModel( self ):
        if self.db is not None:
            self.db.Shutdown()
            
            while not self.db.LoopIsFinished():
                time.sleep( 0.1 )
                
            
        
        if self._fast_job_scheduler is not None:
            self._fast_job_scheduler.shutdown()
            
            self._fast_job_scheduler = None
            
        
        if self._slow_job_scheduler is not None:
            self._slow_job_scheduler.shutdown()
            
            self._slow_job_scheduler = None
            
        
        if hasattr( self, 'temp_dir' ):
            HydrusPaths.DeletePath( self.temp_dir )
            
        
        self._model_shutdown = True
        HG.model_shutdown = True
        
    
    def ShutdownView( self ):
        self._view_shutdown = True
        HG.view_shutdown = True
        
        self._ShutdownDaemons()
        
    
    def ShutdownFromServer( self ):
        raise Exception( 'This hydrus application cannot be shut down from the server!' )
        
    
    def SleepCheck( self ):
        with self._sleep_lock:
            if HydrusData.TimeHasPassed( self._timestamps[ 'now_awake' ] ):
                last_sleep_check = self._timestamps[ 'last_sleep_check' ]
                
                if HydrusData.TimeHasPassed( last_sleep_check + 600 ): # it has been way too long since this method last fired, so we've prob been asleep
                    
                    self._just_woke_from_sleep = True
                    
                    self.ResetIdleTimer() # this will stop the background jobs from kicking in as soon as the grace period is over
                    
                    self._timestamps[ 'now_awake' ] = HydrusData.GetNow() + 15 # enough time for ethernet to get back online and all that
                    
                else:
                    self._just_woke_from_sleep = False
                    
                
            
            self._timestamps[ 'last_sleep_check' ] = HydrusData.GetNow()
            
        
    
    def SimulateWakeFromSleepEvent( self ):
        with self._sleep_lock:
            self._timestamps[ 'last_sleep_check' ] = HydrusData.GetNow() - 3600
            
        
    
    def SystemBusy( self ):
        return self._system_busy
        
    
    def ViewIsShutdown( self ):
        return self._view_shutdown
        
    
    def WaitUntilDBEmpty( self ):
        while True:
            if self._model_shutdown:
                raise HydrusExceptions.ShutdownException( 'Application shutting down!' )
                
            elif self.db.JobsQueueEmpty() and not self.db.CurrentlyDoingJob():
                return
                
            else:
                time.sleep( 0.00001 )
                
            
        
    
    def WaitUntilModelFree( self ):
        self.WaitUntilPubSubsEmpty()
        
        self.WaitUntilDBEmpty()
        
    
    def WaitUntilPubSubsEmpty( self ):
        while True:
            if self._model_shutdown:
                raise HydrusExceptions.ShutdownException( 'Application shutting down!' )
                
            elif not self.CurrentlyPubSubbing():
                return
                
            else:
                time.sleep( 0.00001 )
                
            
        
    
    def WakeDaemon( self, name ):
        if name in self._daemon_jobs:
            self._daemon_jobs[ name ].Wake()
            
        
    
    def Write( self, action, *args, **kwargs ):
        return self._Write( action, False, *args, **kwargs )
        
    
    def WriteSynchronous( self, action, *args, **kwargs ):
        return self._Write( action, True, *args, **kwargs )
        
    
    def DAEMONPubSub( self ):
        while not HG.model_shutdown:
            if self._pubsub.WorkToDo():
                try:
                    self.ProcessPubSub()
                    
                except Exception as e:
                    HydrusData.ShowException( e, do_wait = True )
                    
                
            else:
                self._pubsub.WaitOnPub()



class ServerController( HydrusController ):
    def __init__( self, db_dir ):
        HydrusController.__init__( self, db_dir )
        self._name = 'server'
        self._shutdown = False
        HG.server_controller = self
        
    
    def _GetUPnPServices( self ):
        return self._services
        
    
    def _InitDB( self ):
        return ServerDB.DB( self, self.db_dir, 'server' )
        
    
    def StartService( self, service ):
        def TWISTEDDoIt():
            service_key = service.GetServiceKey()
            service_type = service.GetServiceType()
            
            def Start( *args, **kwargs ):
                try:
                    port = service.GetPort()
                    
                    if HydrusNetworking.LocalPortInUse( port ):
                        raise Exception( 'Something was already bound to port ' + str( port ) )
                        
                    
                    if service_type == HC.SERVER_ADMIN:
                        http_factory = ServerServer.HydrusServiceAdmin( service )
                        
                    elif service_type == HC.FILE_REPOSITORY:
                        http_factory = ServerServer.HydrusServiceRepositoryFile( service )
                        
                    elif service_type == HC.TAG_REPOSITORY:
                        http_factory = ServerServer.HydrusServiceRepositoryTag( service )
                        
                    else:
                        return
                        
                    
                    ( ssl_cert_path, ssl_key_path ) = self.db.GetSSLPaths()
                    sslmethod = ssl.SSL.TLSv1_2_METHOD
                    
                    context_factory = ssl.DefaultOpenSSLContextFactory( ssl_key_path, ssl_cert_path, sslmethod )
                    
                    self._service_keys_to_connected_ports[ service_key ] = reactor.listenSSL( port, http_factory, context_factory )
                    
                    if not HydrusNetworking.LocalPortInUse( port ):
                        raise Exception( 'Tried to bind port ' + str( port ) + ' but it failed.' )
                        
                    
                except Exception as e:
                    HydrusData.Print( traceback.format_exc() )
                    
                
            
            if service_key in self._service_keys_to_connected_ports:
                deferred = defer.maybeDeferred( self._service_keys_to_connected_ports[ service_key ].stopListening )
                deferred.addCallback( Start )
                
            else:
                Start()
        
        reactor.callFromThread( TWISTEDDoIt )
        
    
    def StopService( self, service_key ):
        def TWISTEDDoIt():
            deferred = defer.maybeDeferred( self._service_keys_to_connected_ports[ service_key ].stopListening )
            del self._service_keys_to_connected_ports[ service_key ]
            
        reactor.callFromThread( TWISTEDDoIt )
        
    
    def DeleteOrphans( self ):
        self.WriteSynchronous( 'delete_orphans' )
        
    
    def Exit( self ):
        HydrusData.Print( 'Shutting down daemons and services\u2026' )
        self.ShutdownView()
        
        HydrusData.Print( 'Shutting down db\u2026' )
        self.ShutdownModel()
        
        HydrusData.CleanRunningFile( self.db_dir, 'server' )
        
    
    def GetFilesDir( self ):
        return self.db.GetFilesDir()
        
    
    def GetServices( self ):
        return list( self._services )
        
    
    def InitModel( self ):
        HydrusController.InitModel( self )
        
        self._services = self.Read( 'services' )
        
        [ self._admin_service ] = [ service for service in self._services if service.GetServiceType() == HC.SERVER_ADMIN ]
        
        self.server_session_manager = HydrusSessions.HydrusSessionManagerServer()
        
        self._service_keys_to_connected_ports = {}
        
    
    def InitView( self ):
        HydrusController.InitView( self )
        
        port = self._admin_service.GetPort()
        
        if HydrusNetworking.LocalPortInUse( port ):
            HydrusData.Print( 'Something is already bound to port ' + str( port ) + ', so your administration service cannot be started. Please quit the server and retry once the port is clear.' )
            
        else:
            for service in self._services:
                self.StartService( service )
                
        #
        
        job = self.CallRepeating( 5.0, 600.0, self.SyncRepositories )
        self._daemon_jobs[ 'sync_repositories' ] = job
        
        job = self.CallRepeating( 0.0, 30.0, self.SaveDirtyObjects )
        self._daemon_jobs[ 'save_dirty_objects' ] = job
        
        job = self.CallRepeating( 0.0, 86400.0, self.DeleteOrphans )
        self._daemon_jobs[ 'delete_orphans' ] = job
        
    
    def JustWokeFromSleep( self ):
        return False
        
    
    def MaintainDB( self, stop_time = None ):
        stop_time = HydrusData.GetNow() + 10
        self.WriteSynchronous( 'analyze', stop_time )
        
    
    def ReportDataUsed( self, num_bytes ):
        self._admin_service.ServerReportDataUsed( num_bytes )
        
    
    def ReportRequestUsed( self ):
        self._admin_service.ServerReportRequestUsed()
        
    
    def Run( self ):
        HydrusData.RecordRunningStart( self.db_dir, 'server' )
        HydrusData.Print( 'Initialising db\u2026' )
        
        self.InitModel()
        
        HydrusData.Print( 'Initialising daemons and services\u2026' )

        self.InitView()
        
        HydrusData.Print( 'Server is running. Press Ctrl+C to quit.' )
        
        try:
            while not self._model_shutdown and not self._shutdown:
                time.sleep( 1 )
            
        except KeyboardInterrupt:
            HydrusData.Print( 'Received a keyboard interrupt\u2026' )
            
        HydrusData.Print( 'Shutting down controller\u2026' )
        
        self.Exit()
        
    
    def SaveDirtyObjects( self ):
        with HG.dirty_object_lock:
            dirty_services = [ service for service in self._services if service.IsDirty() ]
            
            if len( dirty_services ) > 0:
                self.WriteSynchronous( 'dirty_services', dirty_services )
            
            if len( self.server_session_manager.GetDirtyAccounts() ) > 0:
                self.WriteSynchronous( 'dirty_accounts', dirty_accounts )
                
            
        
    
    def ServerBandwidthOK( self ):
        return self._admin_service.ServerBandwidthOK()
    

    def SetServices( self, services ): # doesn't need the dirty_object_lock because the caller takes it
        self._services = services
        
        self.CallToThread( self.services_upnp_manager.SetServices, self._services )
        
        [ self._admin_service ] = [ service for service in self._services if service.GetServiceType() == HC.SERVER_ADMIN ]
        
        current_service_keys = set( self._service_keys_to_connected_ports.keys() )
        future_service_keys = set( [ service.GetServiceKey() for service in self._services ] )
        stop_service_keys = current_service_keys.difference( future_service_keys )
        
        for service_key in stop_service_keys:
            self.StopService( service_key )
            
        for service in self._services:
            self.StartService( service )
            
    
    def ShutdownView( self ):
        for service in self._services:
            service_key = service.GetServiceKey()
            
            if service_key in self._service_keys_to_connected_ports:
                self.StopService( service_key )
                
        HydrusController.ShutdownView( self )
        
    
    def ShutdownFromServer( self ):
        HydrusData.Print( 'Received a server shut down request\u2026' )
        
        self._shutdown = True
        
    
    def SyncRepositories( self ):
        if HG.server_busy:
            return
            
        repositories = [ service for service in self._services if service.GetServiceType() in HC.REPOSITORIES ]
        
        for service in repositories:
            service.Sync()



class ClientController( HydrusController ):
    def __init__( self, db_dir ):
        self._last_shutdown_was_bad = False
        self._is_booted = False
        self._splash = None
        
        HydrusController.__init__( self, db_dir )
        
        self._name = 'client'
        
        HG.client_controller = self
        
        # just to set up some defaults, in case some db update expects something for an odd yaml-loading reason
        self.options = ClientDefaults.GetClientDefaultOptions()
        self.new_options = ClientOptions.ClientOptions()
        
        HC.options = self.options
        
        self._page_key_lock = threading.Lock()
        
        self._thread_slots[ 'watcher_files' ] = ( 0, 15 )
        self._thread_slots[ 'watcher_check' ] = ( 0, 5 )
        self._thread_slots[ 'gallery_files' ] = ( 0, 15 )
        self._thread_slots[ 'gallery_search' ] = ( 0, 5 )
        
        self._alive_page_keys = set()
        self._closed_page_keys = set()
        
        self._last_mouse_position = None
        self._menu_open = False
        self._previously_idle = False
        self._idle_started = None
        
        self.client_files_manager = None
        self.services_manager = None
        
    
    def _InitDB( self ):
        return ClientDB.DB( self, self.db_dir, 'client' )
        
    
    def _InitTempDir( self ):
        self.temp_dir = ClientPaths.GetTempDir()
        
    
    def _DestroySplash( self ):
        def wx_code( splash ):
            if splash:
                splash.Hide()
                splash.DestroyLater()
                
            
        
        if self._splash is not None:
            splash = self._splash
            self._splash = None
            wx.CallAfter( wx_code, splash )
            
    
    def _GetUPnPServices( self ):
        return self.services_manager.GetServices( ( HC.LOCAL_BOORU, HC.CLIENT_API_SERVICE ) )
        
    
    def _ReportShutdownDaemonsStatus( self ):
        names = { daemon.name for daemon in self._daemons if daemon.is_alive() }
        names = list( names )
        names.sort()
        self.pub( 'splash_set_status_subtext', ', '.join( names ) )
        
    
    def AcquirePageKey( self ):
        with self._page_key_lock:
            page_key = HydrusData.GenerateKey()
            self._alive_page_keys.add( page_key )

            return page_key
            
        
    
    def CallBlockingToWX( self, win, func, *args, **kwargs ):
        def wx_code( win, job_key ):
            try:
                if win is not None and not win:
                    raise HydrusExceptions.WXDeadWindowException( 'Parent Window was destroyed before wx command was called!' )
                    
                result = func( *args, **kwargs )
                
                job_key.SetVariable( 'result', result )
                
            except ( HydrusExceptions.WXDeadWindowException, HydrusExceptions.InsufficientCredentialsException, HydrusExceptions.ShutdownException ) as e:
                job_key.SetVariable( 'error', e )
                
            except Exception as e:
                job_key.SetVariable( 'error', e )
                
                HydrusData.Print( 'CallBlockingToWX just caught this error:' )
                HydrusData.DebugPrint( traceback.format_exc() )
                
            finally:
                job_key.Finish()
                
            
        
        job_key = ClientThreading.JobKey( cancel_on_shutdown = False )
        
        job_key.Begin()
        
        wx.CallAfter( wx_code, win, job_key )
        
        while not job_key.IsDone():
            if self._model_shutdown:
                raise HydrusExceptions.ShutdownException( 'Application is shutting down!' )
                
            time.sleep( 0.05 )
            
        
        if job_key.HasVariable( 'result' ):
            # result can be None, for wx_code that has no return variable
            result = job_key.GetIfHasVariable( 'result' )
            
            return result
            
        error = job_key.GetIfHasVariable( 'error' )
        
        if error is not None:
            raise error
            
        raise HydrusExceptions.ShutdownException()
        
    
    def CallLaterWXSafe( self, window, initial_delay, func, *args, **kwargs ):
        job_scheduler = self._GetAppropriateJobScheduler( initial_delay )
        
        call = HydrusData.Call( func, *args, **kwargs )
        
        job = ClientThreading.WXAwareJob( self, job_scheduler, window, initial_delay, call )
        
        job_scheduler.AddJob( job )
        
        return job
        
    
    def CallRepeatingWXSafe( self, window, initial_delay, period, func, *args, **kwargs ):
        job_scheduler = self._GetAppropriateJobScheduler( period )
        
        call = HydrusData.Call( func, *args, **kwargs )
        
        job = ClientThreading.WXAwareRepeatingJob( self, job_scheduler, window, initial_delay, period, call )
        
        job_scheduler.AddJob( job )
        
        return job
        
    
    def CheckAlreadyRunning( self ):
        while HydrusData.IsAlreadyRunning( self.db_dir, 'client' ):
            self.pub( 'splash_set_status_text', 'client already running' )
            
            def wx_code():
                message = 'It looks like another instance of this client is already running, so this instance cannot start.'
                message += os.linesep * 2
                message += 'If the old instance is closing and does not quit for a _very_ long time, it is usually safe to force-close it from task manager.'
                
                with ClientGUIDialogs.DialogYesNo( self._splash, message, 'The client is already running.', yes_label = 'wait a bit, then try again', no_label = 'forget it' ) as dlg:
                    if dlg.ShowModal() != wx.ID_YES:
                        
                        raise HydrusExceptions.ShutdownException()
                        
                
            self.CallBlockingToWX( self._splash, wx_code )
            
            for i in range( 10, 0, -1 ):
                if not HydrusData.IsAlreadyRunning( self.db_dir, 'client' ):
                    break
                
                self.pub( 'splash_set_status_text', 'waiting ' + str( i ) + ' seconds' )
                
                time.sleep( 1 )
                
            
        
    
    def CheckMouseIdle( self ):
        mouse_position = wx.GetMousePosition()
        
        if self._last_mouse_position is None:
            self._last_mouse_position = mouse_position
            
        elif mouse_position != self._last_mouse_position:
            idle_before_position_update = self.CurrentlyIdle()

            self._timestamps[ 'last_mouse_action' ] = HydrusData.GetNow()
            self._last_mouse_position = mouse_position

            idle_after_position_update = self.CurrentlyIdle()
            move_knocked_us_out_of_idle = ( not idle_before_position_update ) and idle_after_position_update

            if move_knocked_us_out_of_idle:   
                self.pub( 'set_status_bar_dirty' )
                
            
        
    
    def ClosePageKeys( self, page_keys ):
        with self._page_key_lock:
            self._closed_page_keys.update( page_keys )
            
        
    
    def CreateSplash( self ):
        try:
            self._splash = ClientGUI.FrameSplash( self )
            
        except:
            HydrusData.Print( 'There was an error trying to start the splash screen!' )
            HydrusData.Print( traceback.format_exc() )

            raise
            
        
    
    def CurrentlyIdle( self ):
        if HG.force_idle_mode:
            self._idle_started = 0
            return True
        
        if not HydrusData.TimeHasPassed( self._timestamps[ 'boot' ] + 120 ):
            return False
            
        
        idle_normal = self.options[ 'idle_normal' ]
        idle_period = self.options[ 'idle_period' ]
        idle_mouse_period = self.options[ 'idle_mouse_period' ]
        
        if idle_normal:
            currently_idle = True
            
            if idle_period is not None:
                if not HydrusData.TimeHasPassed( self._timestamps[ 'last_user_action' ] + idle_period ):
                    currently_idle = False
                    
                
            
            if idle_mouse_period is not None:
                if not HydrusData.TimeHasPassed( self._timestamps[ 'last_mouse_action' ] + idle_mouse_period ):
                    currently_idle = False
                    
                
            
        else:
            currently_idle = False
            
        
        turning_idle = currently_idle and not self._previously_idle
        self._previously_idle = currently_idle
        
        if turning_idle:
            self._idle_started = HydrusData.GetNow()
            self.pub( 'wake_daemons' )
        
        if not currently_idle:
            self._idle_started = None
            
        return currently_idle
        
    
    def CurrentlyVeryIdle( self ):
        if self._idle_started is not None and HydrusData.TimeHasPassed( self._idle_started + 3600 ):
            return True
        
        return False
        
    
    def DoIdleShutdownWork( self ):
        stop_time = HydrusData.GetNow() + ( self.options[ 'idle_shutdown_max_minutes' ] * 60 )
        
        self.MaintainDB( only_if_idle = False, stop_time = stop_time )
        
        if not self.options[ 'pause_repo_sync' ]:
            services = self.services_manager.GetServices( HC.REPOSITORIES )
            
            for service in services:
                if HydrusData.TimeHasPassed( stop_time ):
                    return
                
                service.SyncProcessUpdates( only_when_idle = False, stop_time = stop_time )
                
        self.Write( 'last_shutdown_work_time', HydrusData.GetNow() )
        
    
    def Exit( self ):
        if HG.emergency_exit:
            self.ShutdownView()
            self.ShutdownModel()
            
            HydrusData.CleanRunningFile( self.db_dir, 'client' )
            
        else:
            try:
                last_shutdown_work_time = self.Read( 'last_shutdown_work_time' )
                shutdown_work_period = self.new_options.GetInteger( 'shutdown_work_period' )
                we_can_shutdown_work = HydrusData.TimeHasPassed( last_shutdown_work_time + shutdown_work_period )
                idle_shutdown_action = self.options[ 'idle_shutdown' ]
                
                if we_can_shutdown_work and idle_shutdown_action in ( CC.IDLE_ON_SHUTDOWN, CC.IDLE_ON_SHUTDOWN_ASK_FIRST ):
                    idle_shutdown_max_minutes = self.options[ 'idle_shutdown_max_minutes' ]
                    
                    time_to_stop = HydrusData.GetNow() + ( idle_shutdown_max_minutes * 60 )
                    
                    work_to_do = self.GetIdleShutdownWorkDue( time_to_stop )
                    
                    if len( work_to_do ) > 0:
                        if idle_shutdown_action == CC.IDLE_ON_SHUTDOWN_ASK_FIRST:
                            text = 'Is now a good time for the client to do up to ' + HydrusData.ToHumanInt( idle_shutdown_max_minutes ) + ' minutes\' maintenance work? (Will auto-no in 15 seconds)'
                            text += os.linesep * 2
                            text += 'The outstanding jobs appear to be:'
                            text += os.linesep * 2
                            text += os.linesep.join( work_to_do )
                            
                            with ClientGUIDialogs.DialogYesNo( self._splash, text, title = 'Maintenance is due' ) as dlg_yn:
                                job = self.CallLaterWXSafe( dlg_yn, 15, dlg_yn.EndModal, wx.ID_NO )
                                
                                try:
                                    if dlg_yn.ShowModal() == wx.ID_YES:
                                        HG.do_idle_shutdown_work = True
                                        
                                    else:
                                        # if they said no, don't keep asking
                                        self.Write( 'last_shutdown_work_time', HydrusData.GetNow() )
                                        
                                    
                                finally:
                                    job.Cancel()
                            
                        else:
                            HG.do_idle_shutdown_work = True
                
                self.CallToThreadLongRunning( self.THREADExitEverything )
                
            except:
                self._DestroySplash()
                
                HydrusData.DebugPrint( traceback.format_exc() )
                
                HG.emergency_exit = True
                
                self.Exit()
                
            
        
    
    def GetApp( self ):
        return self._app
        
    
    def GetClipboardText( self ):
        if wx.TheClipboard.Open():
            data = wx.TextDataObject()
            
            wx.TheClipboard.GetData( data )
            wx.TheClipboard.Close()
            
            text = data.GetText()
            
            return text
            
        else:
            raise Exception( 'I could not get permission to access the clipboard.' )
            
        
    
    def GetCommandFromShortcut( self, shortcut_names, shortcut ):
        return self._shortcuts_manager.GetCommand( shortcut_names, shortcut )
        
    
    def GetGUI( self ):
        return self.gui
        
    
    def GetIdleShutdownWorkDue( self, time_to_stop ):
        work_to_do = []
        work_to_do.extend( self.Read( 'maintenance_due', time_to_stop ) )
        
        services = self.services_manager.GetServices( HC.REPOSITORIES )
        
        for service in services:
            if service.CanDoIdleShutdownWork():
                work_to_do.append( service.GetName() + ' repository processing' )
                
        return work_to_do
        
    
    def GetNewOptions( self ):
        return self.new_options
        
    
    def InitClientFilesManager( self ):
        def wx_code( missing_locations ):
            with ClientGUITopLevelWindows.DialogManage( None, 'repair file system' ) as dlg:
                panel = ClientGUIScrolledPanelsManagement.RepairFileSystemPanel( dlg, missing_locations )
                
                dlg.SetPanel( panel )
                
                if dlg.ShowModal() == wx.ID_OK:
                    self.client_files_manager = ClientCaches.ClientFilesManager( self )
                    missing_locations = self.client_files_manager.GetMissing()
                    
                else:
                    raise HydrusExceptions.ShutdownException( 'File system failed, user chose to quit.' )
                    
            return missing_locations
            
        self.client_files_manager = ClientCaches.ClientFilesManager( self )
        missing_locations = self.client_files_manager.GetMissing()
        
        while len( missing_locations ) > 0:
            missing_locations = self.CallBlockingToWX( self._splash, wx_code, missing_locations )
            
        
    
    def InitModel( self ):
        self.pub( 'splash_set_title_text', 'booting db\u2026' )
        
        HydrusController.HydrusController.InitModel( self )
        
        self.pub( 'splash_set_status_text', 'initialising managers' )
        self.pub( 'splash_set_status_subtext', 'services' )
        
        self.services_manager = ClientCaches.ServicesManager( self )
        
        self.pub( 'splash_set_status_subtext', 'options' )
        
        self.options = self.Read( 'options' )
        self.new_options = self.Read( 'serialisable', HydrusSerialisable.SERIALISABLE_TYPE_CLIENT_OPTIONS )
        
        HC.options = self.options
        
        if self.new_options.GetBoolean( 'use_system_ffmpeg' ):
            if HydrusVideoHandling.FFMPEG_PATH.startswith( HC.BIN_DIR ):
                HydrusVideoHandling.FFMPEG_PATH = os.path.basename( HydrusVideoHandling.FFMPEG_PATH )
        
        self.pub( 'splash_set_status_subtext', 'client files' )
        
        self.InitClientFilesManager()
        
        #
        
        self.pub( 'splash_set_status_subtext', 'network' )
        
        self.parsing_cache = ClientCaches.ParsingCache()
        
        client_api_manager = self.Read( 'serialisable', HydrusSerialisable.SERIALISABLE_TYPE_CLIENT_API_MANAGER )
        
        if client_api_manager is None:
            client_api_manager = ClientAPI.APIManager()
            client_api_manager._dirty = True
            
            wx.SafeShowMessage( 'Problem loading object', 'Your client api manager was missing on boot! I have recreated a new empty one. Please check that your hard drive and client are ok and let the hydrus dev know the details if there is a mystery.' )
        
        self.client_api_manager = client_api_manager
        
        bandwidth_manager = self.Read( 'serialisable', HydrusSerialisable.SERIALISABLE_TYPE_NETWORK_BANDWIDTH_MANAGER )
        
        if bandwidth_manager is None:
            bandwidth_manager = ClientNetworkingBandwidth.NetworkBandwidthManager()
            ClientDefaults.SetDefaultBandwidthManagerRules( bandwidth_manager )
            bandwidth_manager._dirty = True
            
            wx.SafeShowMessage( 'Problem loading object', 'Your bandwidth manager was missing on boot! I have recreated a new empty one with default rules. Please check that your hard drive and client are ok and let the hydrus dev know the details if there is a mystery.' )
        
        session_manager = self.Read( 'serialisable', HydrusSerialisable.SERIALISABLE_TYPE_NETWORK_SESSION_MANAGER )
        
        if session_manager is None:
            session_manager = ClientNetworkingSessions.NetworkSessionManager()
            session_manager._dirty = True
            
            wx.SafeShowMessage( 'Problem loading object', 'Your session manager was missing on boot! I have recreated a new empty one. Please check that your hard drive and client are ok and let the hydrus dev know the details if there is a mystery.' )
            
        domain_manager = self.Read( 'serialisable', HydrusSerialisable.SERIALISABLE_TYPE_NETWORK_DOMAIN_MANAGER )
        
        if domain_manager is None:
            domain_manager = ClientNetworkingDomain.NetworkDomainManager()
            ClientDefaults.SetDefaultDomainManagerData( domain_manager )
            domain_manager._dirty = True
            
            wx.SafeShowMessage( 'Problem loading object', 'Your domain manager was missing on boot! I have recreated a new empty one. Please check that your hard drive and client are ok and let the hydrus dev know the details if there is a mystery.' )
        
        domain_manager.Initialise()
        
        login_manager = self.Read( 'serialisable', HydrusSerialisable.SERIALISABLE_TYPE_NETWORK_LOGIN_MANAGER )
        
        if login_manager is None:
            login_manager = ClientNetworkingLogin.NetworkLoginManager()
            ClientDefaults.SetDefaultLoginManagerScripts( login_manager )
            login_manager._dirty = True
            
            wx.SafeShowMessage( 'Problem loading object', 'Your login manager was missing on boot! I have recreated a new empty one. Please check that your hard drive and client are ok and let the hydrus dev know the details if there is a mystery.' )
        
        login_manager.Initialise()
        
        self.network_engine = ClientNetworking.NetworkEngine( self, bandwidth_manager, session_manager, domain_manager, login_manager )
        
        self.CallToThreadLongRunning( self.network_engine.MainLoop )
        
        #
        
        self._shortcuts_manager = ClientCaches.ShortcutsManager( self )
        
        self.local_booru_manager = ClientCaches.LocalBooruCache( self )
        
        self.file_viewing_stats_manager = ClientCaches.FileViewingStatsManager( self )
        
        self.pub( 'splash_set_status_subtext', 'tag censorship' )
        
        self.tag_censorship_manager = ClientCaches.TagCensorshipManager( self )
        
        self.pub( 'splash_set_status_subtext', 'tag siblings' )
        
        self.tag_siblings_manager = ClientCaches.TagSiblingsManager( self )
        
        self.pub( 'splash_set_status_subtext', 'tag parents' )
        
        self.tag_parents_manager = ClientCaches.TagParentsManager( self )
        self._managers[ 'undo' ] = ClientCaches.UndoManager( self )
        
        def wx_code():
            self._caches[ 'images' ] = ClientCaches.RenderedImageCache( self )
            self._caches[ 'thumbnail' ] = ClientCaches.ThumbnailCache( self )
            self.bitmap_manager = ClientCaches.BitmapManager( self )
            
            CC.GlobalBMPs.STATICInitialise()
            
        
        self.pub( 'splash_set_status_subtext', 'image caches' )
        
        self.CallBlockingToWX( self._splash, wx_code )
        
        self.sub( self, 'ToClipboard', 'clipboard' )
        self.sub( self, 'RestartClientServerService', 'restart_client_server_service' )
        
    
    def InitView( self ):
        if self.options[ 'password' ] is not None:
            self.pub( 'splash_set_status_text', 'waiting for password' )
            
            def wx_code_password():
                while True:
                    with wx.PasswordEntryDialog( self._splash, 'Enter your password', 'Enter password' ) as dlg:
                        if dlg.ShowModal() == wx.ID_OK:
                            password_bytes = bytes( dlg.GetValue(), 'utf-8' )
                            
                            if hashlib.sha256( password_bytes ).digest() == self.options[ 'password' ]:
                                break
                                
                            
                        else:
                            raise HydrusExceptions.InsufficientCredentialsException( 'Bad password check' )
                            
            self.CallBlockingToWX( self._splash, wx_code_password )
            
        
        self.pub( 'splash_set_title_text', 'booting gui\u2026' )
        
        def wx_code_gui():
            self.gui = ClientGUI.FrameGUI( self )
            self.ResetIdleTimer()
            
        self.CallBlockingToWX( self._splash, wx_code_gui )
        
        # ShowText will now popup as a message, as popup message manager has overwritten the hooks
        
        HydrusController.HydrusController.InitView( self )
        
        self._listening_services = {}
        
        self.RestartClientServerService( CC.LOCAL_BOORU_SERVICE_KEY )
        self.RestartClientServerService( CC.CLIENT_API_SERVICE_KEY )
        
        if not HG.no_daemons:
            self._daemons.append( HydrusThreading.DAEMONForegroundWorker( self, 'DownloadFiles', ClientDaemons.DAEMONDownloadFiles, ( 'notify_new_downloads', 'notify_new_permissions' ) ) )
            self._daemons.append( HydrusThreading.DAEMONForegroundWorker( self, 'SynchroniseSubscriptions', ClientDaemons.DAEMONSynchroniseSubscriptions, ( 'notify_restart_subs_sync_daemon', 'notify_new_subscriptions' ), period = 4 * 3600, init_wait = 60, pre_call_wait = 3 ) )
            self._daemons.append( HydrusThreading.DAEMONForegroundWorker( self, 'MaintainTrash', ClientDaemons.DAEMONMaintainTrash, init_wait = 120 ) )
            self._daemons.append( HydrusThreading.DAEMONForegroundWorker( self, 'SynchroniseRepositories', ClientDaemons.DAEMONSynchroniseRepositories, ( 'notify_restart_repo_sync_daemon', 'notify_new_permissions' ), period = 4 * 3600, pre_call_wait = 1 ) )
            
        
        job = self.CallRepeating( 5.0, 180.0, ClientDaemons.DAEMONCheckImportFolders )
        job.WakeOnPubSub( 'notify_restart_import_folders_daemon' )
        job.WakeOnPubSub( 'notify_new_import_folders' )
        job.ShouldDelayOnWakeup( True )
        self._daemon_jobs[ 'import_folders' ] = job
        
        job = self.CallRepeating( 5.0, 180.0, ClientDaemons.DAEMONCheckExportFolders )
        job.WakeOnPubSub( 'notify_restart_export_folders_daemon' )
        job.WakeOnPubSub( 'notify_new_export_folders' )
        job.ShouldDelayOnWakeup( True )
        self._daemon_jobs[ 'export_folders' ] = job
        
        job = self.CallRepeating( 0.0, 30.0, self.SaveDirtyObjects )
        job.WakeOnPubSub( 'important_dirt_to_clean' )
        self._daemon_jobs[ 'save_dirty_objects' ] = job
        
        job = self.CallRepeating( 5.0, 3600.0, self.SynchroniseAccounts )
        job.ShouldDelayOnWakeup( True )
        job.WakeOnPubSub( 'notify_unknown_accounts' )
        self._daemon_jobs[ 'synchronise_accounts' ] = job
        
        job = self.CallRepeatingWXSafe( self, 10.0, 10.0, self.CheckMouseIdle )
        self._daemon_jobs[ 'check_mouse_idle' ] = job
        
        if self.db.IsFirstStart():
            message = 'Hi, this looks like the first time you have started the hydrus client.'
            message += os.linesep * 2
            message += 'Don\'t forget to check out the help if you haven\'t already--it has an extensive \'getting started\' section.'
            message += os.linesep * 2
            message += 'To dismiss popup messages like this, right-click them.'
            
            HydrusData.ShowText( message )
            
        
        if self.db.IsDBUpdated():
            HydrusData.ShowText( 'The client has updated to version ' + str( HC.SOFTWARE_VERSION ) + '!' )
            
        
        for message in self.db.GetInitialMessages():
            HydrusData.ShowText( message )
        
    
    def IsBooted( self ):
        return self._is_booted
        
    
    def LastShutdownWasBad( self ):
        return self._last_shutdown_was_bad
        
    
    def MaintainDB( self, only_if_idle = True, stop_time = None ):
        if only_if_idle and not self.GoodTimeToDoBackgroundWork():
            return
        
        if self.new_options.GetBoolean( 'maintain_similar_files_duplicate_pairs_during_idle' ):
            phashes_stop_time = stop_time
            
            if phashes_stop_time is None:
                phashes_stop_time = HydrusData.GetNow() + 15
                
            
            self.WriteSynchronous( 'maintain_similar_files_phashes', stop_time = phashes_stop_time )
            
            tree_stop_time = stop_time
            
            if tree_stop_time is None:
                tree_stop_time = HydrusData.GetNow() + 30
                
            
            self.WriteSynchronous( 'maintain_similar_files_tree', stop_time = tree_stop_time, abandon_if_other_work_to_do = True )
            
            search_distance = self.new_options.GetInteger( 'similar_files_duplicate_pairs_search_distance' )
            search_stop_time = stop_time
            
            if search_stop_time is None:
                search_stop_time = HydrusData.GetNow() + 60
                
            self.WriteSynchronous( 'maintain_similar_files_duplicate_pairs', search_distance, stop_time = search_stop_time, abandon_if_other_work_to_do = True )
            
        if stop_time is None or not HydrusData.TimeHasPassed( stop_time ):
            self.WriteSynchronous( 'maintain_file_reparsing', stop_time = stop_time )
        
        if stop_time is None or not HydrusData.TimeHasPassed( stop_time ):
            self.WriteSynchronous( 'vacuum', stop_time = stop_time )
        
        if stop_time is None or not HydrusData.TimeHasPassed( stop_time ):
            self.WriteSynchronous( 'analyze', stop_time = stop_time )
        
        if stop_time is None or not HydrusData.TimeHasPassed( stop_time ):
            if HydrusData.TimeHasPassed( self._timestamps[ 'last_service_info_cache_fatten' ] + ( 60 * 20 ) ):
                self.pub( 'splash_set_status_text', 'fattening service info' )
                
                services = self.services_manager.GetServices()
                
                for service in services:
                    self.pub( 'splash_set_status_subtext', service.GetName() )
                    
                    try: self.Read( 'service_info', service.GetServiceKey() )
                    except: pass # sometimes this breaks when a service has just been removed and the client is closing, so ignore the error
                    
                self._timestamps[ 'last_service_info_cache_fatten' ] = HydrusData.GetNow()
                
    
    def MaintainMemoryFast( self ):
        HydrusController.HydrusController.MaintainMemoryFast( self )
        self.parsing_cache.CleanCache()
        
    
    def MaintainMemorySlow( self ):
        HydrusController.HydrusController.MaintainMemorySlow( self )
        
        if HydrusData.TimeHasPassed( self._timestamps[ 'last_page_change' ] + 30 * 60 ):
            self.pub( 'delete_old_closed_pages' )
            self._timestamps[ 'last_page_change' ] = HydrusData.GetNow()
            
        disk_cache_maintenance_mb = self.new_options.GetNoneableInteger( 'disk_cache_maintenance_mb' )
        
        if disk_cache_maintenance_mb is not None and not self._view_shutdown:
            cache_period = 3600
            disk_cache_stop_time = HydrusData.GetNow() + 2
            
            if HydrusData.TimeHasPassed( self._timestamps[ 'last_disk_cache_population' ] + cache_period ):
                self.Read( 'load_into_disk_cache', stop_time = disk_cache_stop_time, caller_limit = disk_cache_maintenance_mb * 1024 * 1024 )
                self._timestamps[ 'last_disk_cache_population' ] = HydrusData.GetNow()
        
    
    def MenuIsOpen( self ):
        return self._menu_open
        
    
    def PageAlive( self, page_key ):
        with self._page_key_lock:
            return page_key in self._alive_page_keys
    
    def PageClosedButNotDestroyed( self, page_key ):
        with self._page_key_lock:
            return page_key in self._closed_page_keys
    
    def PopupMenu( self, window, menu ):
        if menu.GetMenuItemCount() > 0:
            self._menu_open = True
            
            window.PopupMenu( menu )
            
            self._menu_open = False
        
        ClientGUIMenus.DestroyMenu( window, menu )
        
    
    def PrepStringForDisplay( self, text ):
        return text.lower()
        
    
    def ProcessPubSub( self ):
        self.CallBlockingToWX( None, self._pubsub.Process )
        
    
    def RefreshServices( self ):
        self.services_manager.RefreshServices()
        
    
    def ReleasePageKey( self, page_key ):
        with self._page_key_lock:
            self._alive_page_keys.discard( page_key )
            self._closed_page_keys.discard( page_key )
            
        
    
    def ResetPageChangeTimer( self ):
        self._timestamps[ 'last_page_change' ] = HydrusData.GetNow()
        
    
    def RestartClientServerService( self, service_key ):
        service = self.services_manager.GetService( service_key )
        service_type = service.GetServiceType()
        
        name = service.GetName()
        
        port = service.GetPort()
        allow_non_local_connections = service.AllowsNonLocalConnections()
        
        def TWISTEDRestartServer():
            def StartServer( *args, **kwargs ):
                try:
                    if HydrusNetworking.LocalPortInUse( port ):
                        text = 'The client\'s {} could not start because something was already bound to port {}.'.format( name, port )
                        text += os.linesep * 2
                        text += 'This usually means another hydrus client is already running and occupying that port. It could be a previous instantiation of this client that has yet to completely shut itself down.'
                        text += os.linesep * 2
                        text += 'You can change the port this service tries to host on under services->manage services.'
                        
                        HydrusData.ShowText( text )
                        
                        return
                        
                    
                    from . import ClientLocalServer
                    
                    if service_type == HC.LOCAL_BOORU:
                        
                        twisted_server = ClientLocalServer.HydrusServiceBooru( service, allow_non_local_connections = allow_non_local_connections )
                        
                    elif service_type == HC.CLIENT_API_SERVICE:
                        
                        twisted_server = ClientLocalServer.HydrusServiceClientAPI( service, allow_non_local_connections = allow_non_local_connections )
                        
                    
                    listening_connection = reactor.listenTCP( port, twisted_server )
                    
                    self._listening_services[ service_key ] = listening_connection
                    
                    if not HydrusNetworking.LocalPortInUse( port ):
                        
                        text = 'Tried to bind port ' + str( port ) + ' for the local booru, but it appeared to fail. It could be a firewall or permissions issue, or perhaps another program was quietly already using it.'
                        
                        HydrusData.ShowText( text )
                        
                    
                except Exception as e:
                    wx.CallAfter( HydrusData.ShowException, e )
                    
                
            
            if service_key in self._listening_services:
                listening_connection = self._listening_services[ service_key ]
                
                del self._listening_services[ service_key ]
                
                deferred = defer.maybeDeferred( listening_connection.stopListening )
                
                if port is not None:
                    deferred.addCallback( StartServer )
                    
                
            else:
                if port is not None:
                    StartServer()
                    
                
            
        
        if HG.twisted_is_broke:
            HydrusData.ShowText( 'Twisted failed to import, so could not start the {}! Please contact hydrus dev!'.format( name ) )
            
        else:
            reactor.callFromThread( TWISTEDRestartServer )
            
        
    
    def RestoreDatabase( self ):
        restore_intro = ''
        
        with wx.DirDialog( self.gui, 'Select backup location.' ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                path = dlg.GetPath()
                
                text = 'Are you sure you want to restore a backup from "' + path + '"?'
                text += os.linesep * 2
                text += 'Everything in your current database will be deleted!'
                text += os.linesep * 2
                text += 'The gui will shut down, and then it will take a while to complete the restore. Once it is done, the client will restart.'
                
                with ClientGUIDialogs.DialogYesNo( self.gui, text ) as dlg_yn:
                    if dlg_yn.ShowModal() == wx.ID_YES:
                        
                        def THREADRestart():
                            
                            while not self.db.LoopIsFinished():
                                
                                time.sleep( 0.1 )
                                
                            
                            self.db.RestoreBackup( path )
                            
                            while not HG.shutdown_complete:
                                
                                time.sleep( 0.1 )
                                
                            
                            HydrusData.RestartProcess()
                            
                        
                        self.CallToThreadLongRunning( THREADRestart )
                        
                        wx.CallAfter( self.gui.Exit )
                        
                    
                
            
        
    
    def Run( self ):
        self._app = wx.App()
        
        self._app.locale = wx.Locale( wx.LANGUAGE_DEFAULT ) # Very important to init this here and keep it non garbage collected
        
        # do not import locale here and try anything clever--assume that bad locale formatting is due to OS-level mess-up, not mine
        # wx locale is supposed to set it all up nice, so if someone's doesn't, explore that and find the external solution
        
        HydrusData.Print( 'booting controller\u2026' )
        
        self.frame_icon = wx.Icon( os.path.join( HC.STATIC_DIR, 'hydrus_32_non-transparent.png' ), wx.BITMAP_TYPE_PNG )
        
        self.CreateSplash()
        
        self.CallToThreadLongRunning( self.THREADBootEverything )
        
        self._app.MainLoop()
        
        HydrusData.DebugPrint( 'shutting down controller\u2026' )
        
    
    def SaveDirtyObjects( self ):
        with HG.dirty_object_lock:
            dirty_services = [ service for service in self.services_manager.GetServices() if service.IsDirty() ]
            
            if len( dirty_services ) > 0:
                self.WriteSynchronous( 'dirty_services', dirty_services )
                
            
            if self.client_api_manager.IsDirty():
                self.WriteSynchronous( 'serialisable', self.client_api_manager )
                
                self.client_api_manager.SetClean()
                
            
            if self.network_engine.bandwidth_manager.IsDirty():
                self.WriteSynchronous( 'serialisable', self.network_engine.bandwidth_manager )
                
                self.network_engine.bandwidth_manager.SetClean()
                
            
            if self.network_engine.domain_manager.IsDirty():
                self.WriteSynchronous( 'serialisable', self.network_engine.domain_manager )
                
                self.network_engine.domain_manager.SetClean()
                
            
            if self.network_engine.login_manager.IsDirty():
                self.WriteSynchronous( 'serialisable', self.network_engine.login_manager )
                
                self.network_engine.login_manager.SetClean()
                
            
            if self.network_engine.session_manager.IsDirty():
                self.WriteSynchronous( 'serialisable', self.network_engine.session_manager )
                
                self.network_engine.session_manager.SetClean()
                
            
        
    
    def SetServices( self, services ):
        with HG.dirty_object_lock:
            upnp_services = [ service for service in services if service.GetServiceType() in ( HC.LOCAL_BOORU, HC.CLIENT_API_SERVICE ) ]
            
            self.CallToThread( self.services_upnp_manager.SetServices, upnp_services )
            
            self.WriteSynchronous( 'update_services', services )
            
            self.services_manager.RefreshServices()
            
        
    
    def ShutdownModel( self ):
        if not HG.emergency_exit:
            self.file_viewing_stats_manager.Flush()
            
            self.SaveDirtyObjects()
            
        
        HydrusController.HydrusController.ShutdownModel( self )
        
    
    def ShutdownView( self ):
        if not HG.emergency_exit:
            self.pub( 'splash_set_status_text', 'waiting for daemons to exit' )
            
            self._ShutdownDaemons()
            
            if HG.do_idle_shutdown_work:
                try:
                    self.DoIdleShutdownWork()
                    
                except:
                    ClientData.ReportShutdownException()
                    
                
            
        
        HydrusController.HydrusController.ShutdownView( self )
        
    
    def SynchroniseAccounts( self ):
        services = self.services_manager.GetServices( HC.RESTRICTED_SERVICES )
        
        for service in services:
            if HydrusThreading.IsThreadShuttingDown():
                return
                
            
            service.SyncAccount()
            
        
    
    def SystemBusy( self ):
        if HG.force_idle_mode:
            return False
            
        
        max_cpu = self.options[ 'idle_cpu_max' ]
        
        if max_cpu is None:
            self._system_busy = False
            
        else:
            if HydrusData.TimeHasPassed( self._timestamps[ 'last_cpu_check' ] + 60 ):
                cpu_times = psutil.cpu_percent( percpu = True )
                
                if True in ( cpu_time > max_cpu for cpu_time in cpu_times ):
                    self._system_busy = True
                    
                else:
                    self._system_busy = False
                    
                
                self._timestamps[ 'last_cpu_check' ] = HydrusData.GetNow()
                
            
        
        return self._system_busy
        
    
    def THREADBootEverything( self ):
        try:
            self.CheckAlreadyRunning()
            
            self._last_shutdown_was_bad = HydrusData.LastShutdownWasBad( self.db_dir, 'client' )
            
            HydrusData.RecordRunningStart( self.db_dir, 'client' )
            
            self.InitModel()
            
            self.InitView()
            
            self._is_booted = True
            
        except ( HydrusExceptions.InsufficientCredentialsException, HydrusExceptions.ShutdownException ) as e:
            HydrusData.Print( e )
            
            HG.emergency_exit = True
            
            self.Exit()
            
        except Exception as e:
            text = 'A serious error occurred while trying to start the program. The error will be shown next in a window. More information may have been written to client.log.'
            
            HydrusData.DebugPrint( 'If the db crashed, another error may be written just above ^.' )
            HydrusData.DebugPrint( text )
            
            HydrusData.DebugPrint( traceback.format_exc() )
            
            wx.SafeShowMessage( 'boot error', text )
            wx.SafeShowMessage( 'boot error', traceback.format_exc() )
            
            HG.emergency_exit = True
            
            self.Exit()
            
        finally:
            self._DestroySplash()
            
        
    
    def THREADExitEverything( self ):
        try:
            gc.collect()
            
            self.pub( 'splash_set_title_text', 'shutting down gui\u2026' )
            
            self.ShutdownView()
            
            self.pub( 'splash_set_title_text', 'shutting down db\u2026' )
            
            self.ShutdownModel()
            
            self.pub( 'splash_set_title_text', 'cleaning up\u2026' )
            
            HydrusData.CleanRunningFile( self.db_dir, 'client' )
            
        except ( HydrusExceptions.InsufficientCredentialsException, HydrusExceptions.ShutdownException ):
            pass
            
        except:
            ClientData.ReportShutdownException()
            
        finally:
            self._DestroySplash()
            
        
    
    def ToClipboard( self, data_type, data ):
        # need this cause can't do it in a non-gui thread
        
        if data_type == 'paths':
            paths = data
            
            if wx.TheClipboard.Open():
                data = wx.DataObjectComposite()
                
                file_data = wx.FileDataObject()
                
                for path in paths: file_data.AddFile( path )
                
                text_data = wx.TextDataObject( os.linesep.join( paths ) )
                
                data.Add( file_data, True )
                data.Add( text_data, False )
                
                wx.TheClipboard.SetData( data )
                
                wx.TheClipboard.Close()
                
            else:
                wx.MessageBox( 'Could not get permission to access the clipboard!' )
                
            
        elif data_type == 'text':
            text = data
            
            if wx.TheClipboard.Open():
                data = wx.TextDataObject( text )
                
                wx.TheClipboard.SetData( data )
                
                wx.TheClipboard.Close()
                
            else:
                wx.MessageBox( 'I could not get permission to access the clipboard.' )
                
            
        elif data_type == 'bmp':
            media = data
            
            image_renderer = self.GetCache( 'images' ).GetImageRenderer( media )
            
            def CopyToClipboard():
                if wx.TheClipboard.Open():
                    wx_bmp = image_renderer.GetWXBitmap()
                    
                    data = wx.BitmapDataObject( wx_bmp )
                    
                    wx.TheClipboard.SetData( data )
                    
                    wx.TheClipboard.Close()
                    
                else:
                    wx.MessageBox( 'I could not get permission to access the clipboard.' )
                    
                
            
            def THREADWait():
                # have to do this in thread, because the image needs the wx event queue to render
                
                start_time = time.time()
                
                while not image_renderer.IsReady():
                    if HydrusData.TimeHasPassed( start_time + 15 ):
                        raise Exception( 'The image did not render in fifteen seconds, so the attempt to copy it to the clipboard was abandoned.' )
                        
                    time.sleep( 0.1 )
                    
                wx.CallAfter( CopyToClipboard )
            
            self.CallToThread( THREADWait )
            
        
    def UnclosePageKeys( self, page_keys ):
        with self._page_key_lock:
            self._closed_page_keys.difference_update( page_keys )
            
    
    def WaitUntilViewFree( self ):
        self.WaitUntilModelFree()
        
        self.WaitUntilThumbnailsFree()
        
    
    def WaitUntilThumbnailsFree( self ):
        while True:
            if self._view_shutdown:
                raise HydrusExceptions.ShutdownException( 'Application shutting down!' )
                
            elif not self._caches[ 'thumbnail' ].DoingWork():
                return
                
            else:
                time.sleep( 0.00001 )
            
    
    def Write( self, action, *args, **kwargs ):
        if action == 'content_updates':
            self._managers[ 'undo' ].AddCommand( 'content_updates', *args, **kwargs )
            
        return HydrusController.Write( self, action, *args, **kwargs )
        

### HELPER FUNCS ###

def ProcessStartingAction( db_dir, action ):
    already_running = HydrusData.IsAlreadyRunning( db_dir, 'server' )
    
    if action == 'start':
        if already_running:
            HydrusData.Print( 'The server is already running. Would you like to [s]top it, [r]estart it, or e[x]it?' )
            
            answer = input()
            
            if len( answer ) > 0:
                answer = answer[0]
                
                if answer == 's':
                    return 'stop'
                    
                elif answer == 'r':
                    return 'restart'

            raise HydrusExceptions.ShutdownException( 'Exiting!' )
            
        else:
            return action
            
        
    elif action == 'stop':
        if already_running:
            return action
            
        else:
            raise HydrusExceptions.ShutdownException( 'The server is not running, so it cannot be stopped!' )
            
        
    elif action == 'restart':
        if already_running:
            return action
            
        else:
            return 'start'
            
    
def ShutdownSiblingInstance( db_dir ):
    port_found = False
    ports = HydrusData.GetSiblingProcessPorts( db_dir, 'server' )
    
    if ports is None:
        raise HydrusExceptions.ShutdownException( 'Could not figure out the existing server\'s ports, so could not shut it down!' )
        
    session = requests.Session()
    session.verify = False
    
    for port in ports:
        try:
            r = session.get( 'https://127.0.0.1:' + str( port ) + '/' )
            server_name = r.headers[ 'Server' ]
            
        except:
            text = 'Could not contact existing server\'s port ' + str( port ) + '!'
            text += os.linesep
            text += traceback.format_exc()
            
            raise HydrusExceptions.ShutdownException( text )
        
        if 'server administration' in server_name:
            port_found = True
            HydrusData.Print( 'Sending shut down instruction\u2026' )
            r = session.post( 'https://127.0.0.1:' + str( port ) + '/shutdown' )
            
            if not r.ok:
                text = 'When told to shut down, the existing server gave an error!'
                text += os.linesep
                text += r.text
                
                raise HydrusExceptions.ShutdownException( text )
            
            time_waited = 0
            
            while HydrusData.IsAlreadyRunning( db_dir, 'server' ):
                time.sleep( 1 )
                time_waited += 1
                
                if time_waited > 20:
                    raise HydrusExceptions.ShutdownException( 'Attempted to shut the existing server down, but it took too long!' )
            
            break
            
        
    
    if not port_found:
        raise HydrusExceptions.ShutdownException( 'The existing server did not have an administration service!' )
        
    HydrusData.Print( 'The existing server is shut down!' )