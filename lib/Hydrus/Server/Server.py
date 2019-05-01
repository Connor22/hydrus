### IMPORTS ###
from lib.Hydrus import Constants as HC, Data
from lib.Hydrus.Server import ServerResources

import traceback, time
from twisted.web.server import Request, Site
from twisted.web.resource import Resource

### CONSTANTS ###
LOCAL_DOMAIN = HydrusServerResources.HydrusDomain( True )
REMOTE_DOMAIN = HydrusServerResources.HydrusDomain( False )

### CODE ###
class HydrusRequest( Request ):
    
    def __init__( self, *args, **kwargs ):
        
        Request.__init__( self, *args, **kwargs )
        
        self.start_time = time.clock()
        self.parsed_request_args = None
        self.hydrus_response_context = None
        self.hydrus_account = None
        
    
class HydrusRequestLogging( HydrusRequest ):
    
    def finish( self ):
        
        HydrusRequest.finish( self )
        
        host = self.getHost()
        
        if self.hydrus_response_context is not None:
            
            status_text = str( self.hydrus_response_context.GetStatusCode() )
            
        elif hasattr( self, 'code' ):
            
            status_text = str( self.code )
            
        else:
            
            status_text = '200'
            
        
        message = str( host.port ) + ' ' + str( self.method, 'utf-8' ) + ' ' + str( self.path, 'utf-8' ) + ' ' + status_text + ' in ' + HydrusData.TimeDeltaToPrettyTimeDelta( time.clock() - self.start_time )
        
        HydrusData.Print( message )
        
    
class HydrusService( Site ):
    
    def __init__( self, service ):
        
        self._service = service
        
        root = self._InitRoot()
        
        Site.__init__( self, root )
        
        if service.LogsRequests():
            
            self.requestFactory = HydrusRequestLogging
            
        else:
            
            self.requestFactory = HydrusRequest
            
        
    
    def _InitRoot( self ):
        
        root = Resource()
        
        root.putChild( b'', HydrusServerResources.HydrusResourceWelcome( self._service, REMOTE_DOMAIN ) )
        root.putChild( b'favicon.ico', HydrusServerResources.hydrus_favicon )
        root.putChild( b'robots.txt', HydrusServerResources.HydrusResourceRobotsTXT( self._service, REMOTE_DOMAIN ) )
        
        return root

### REMOTE SERVER CLASSES ###
class HydrusServiceRestricted( HydrusService ):
    
    def _InitRoot( self ):
        
        root = HydrusService._InitRoot( self )
        
        root.putChild( b'access_key', ServerServerResources.HydrusResourceAccessKey( self._service, REMOTE_DOMAIN ) )
        root.putChild( b'access_key_verification', ServerServerResources.HydrusResourceAccessKeyVerification( self._service, REMOTE_DOMAIN ) )
        root.putChild( b'session_key', ServerServerResources.HydrusResourceSessionKey( self._service, REMOTE_DOMAIN ) )
        
        root.putChild( b'account', ServerServerResources.HydrusResourceRestrictedAccount( self._service, REMOTE_DOMAIN ) )
        root.putChild( b'account_info', ServerServerResources.HydrusResourceRestrictedAccountInfo( self._service, REMOTE_DOMAIN ) )
        #root.putChild( b'account_modification', ServerServerResources.HydrusResourceRestrictedAccountModification( self._service, REMOTE_DOMAIN ) )
        root.putChild( b'account_types', ServerServerResources.HydrusResourceRestrictedAccountTypes( self._service, REMOTE_DOMAIN ) )
        root.putChild( b'registration_keys', ServerServerResources.HydrusResourceRestrictedRegistrationKeys( self._service, REMOTE_DOMAIN ) )
        
        return root
        
    
class HydrusServiceAdmin( HydrusServiceRestricted ):
    
    def _InitRoot( self ):
        
        root = HydrusServiceRestricted._InitRoot( self )
        
        root.putChild( b'busy', ServerServerResources.HydrusResourceBusyCheck() )
        root.putChild( b'backup', ServerServerResources.HydrusResourceRestrictedBackup( self._service, REMOTE_DOMAIN ) )
        root.putChild( b'services', ServerServerResources.HydrusResourceRestrictedServices( self._service, REMOTE_DOMAIN ) )
        root.putChild( b'shutdown', ServerServerResources.HydrusResourceShutdown( self._service, LOCAL_DOMAIN ) )
        
        return root
        
    
class HydrusServiceRepository( HydrusServiceRestricted ):
    
    def _InitRoot( self ):
        
        root = HydrusServiceRestricted._InitRoot( self )
        
        root.putChild( b'num_petitions', ServerServerResources.HydrusResourceRestrictedNumPetitions( self._service, REMOTE_DOMAIN ) )
        root.putChild( b'petition', ServerServerResources.HydrusResourceRestrictedPetition( self._service, REMOTE_DOMAIN ) )
        root.putChild( b'update', ServerServerResources.HydrusResourceRestrictedUpdate( self._service, REMOTE_DOMAIN ) )
        #root.putChild( b'immediate_update', ServerServerResources.HydrusResourceRestrictedImmediateUpdate( self._service, REMOTE_DOMAIN ) )
        root.putChild( b'metadata', ServerServerResources.HydrusResourceRestrictedMetadataUpdate( self._service, REMOTE_DOMAIN ) )
        
        return root
        
    
class HydrusServiceRepositoryFile( HydrusServiceRepository ):
    
    def _InitRoot( self ):
        
        root = HydrusServiceRepository._InitRoot( self )
        
        root.putChild( b'file', ServerServerResources.HydrusResourceRestrictedRepositoryFile( self._service, REMOTE_DOMAIN ) )
        root.putChild( b'ip', ServerServerResources.HydrusResourceRestrictedIP( self._service, REMOTE_DOMAIN ) )
        root.putChild( b'thumbnail', ServerServerResources.HydrusResourceRestrictedRepositoryThumbnail( self._service, REMOTE_DOMAIN ) )
        
        return root
        
    
class HydrusServiceRepositoryTag( HydrusServiceRepository ):
    
    pass
