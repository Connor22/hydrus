#!/usr/bin/env python3

# This program is free software. It comes without any warranty, to
# the extent permitted by applicable law. You can redistribute it
# and/or modify it under the terms of the Do What The Fuck You Want
# To Public License, Version 2, as published by Sam Hocevar. See
# http://sam.zoy.org/wtfpl/COPYING for more details.

import traceback, os

try:
    #### IMPORTING ####
    from include.Hydrus import Py2To3, Exceptions, Constants as HC,\
     Data, Paths, Globals as HG, Logger        

    import locale, sys, time, threading, argparser, wx

    try:
        from twisted.internet import reactor
    except:
        HG.twisted_is_broke = True
    
    #### DEBUG ####
    try: locale.setlocale( locale.LC_ALL, '' )
    except: pass

    #### EXECUTION ####
    result = SetupArgParser()
    db_dir = SetupDirectories()

    HG.no_daemons = result.no_daemons
    HG.no_wal = result.no_wal
    HG.no_db_temp_files = result.no_db_temp_files
    
    run(result.program)
        
except ( Exceptions.InsufficientCredentialsException, Exceptions.ShutdownException ) as e:
    Data.Print( e )
    
except Exception as e:    
    print( traceback.format_exc() )
    
    if 'db_dir' in locals() and os.path.exists( db_dir ):
        dest_path = os.path.join( db_dir, 'crash.log' )
        with open( dest_path, 'w', encoding = 'utf-8' ) as f:
            f.write( traceback.format_exc() )
            
        print( 'Critical error occurred! Details written to crash.log!' )

#### FUNCTIONS ####

def run( program: str ):
    if program == 'server':
        Py2To3.do_2to3_test()
        from include.Server import Controller
        action = result.action
        action = Controller.ProcessStartingAction( db_dir, action )
    if program == 'client':
        Py2To3.do_2to3_test( wx_error_display_callable = wx.SafeShowMessage )
        from include.Client import Controller

    with Logger.Logger( db_dir, program ) as logger:
        try:
            if program == 'server' && action in ( 'stop', 'restart' ):
                Controller.ShutdownSiblingInstance( db_dir )

            if program == 'client' || program == 'server' && action in ( 'start', 'restart'):
                Data.Print( f'hydrus {program} started' )
                if not HG.twisted_is_broke: threading.Thread( target = reactor.run, name = 'twisted', kwargs = { 'installSignalHandlers' : 0 } ).start()
                controller = Controller.Controller( db_dir )
                controller.run()

        except:
            Data.Print( f'hydrus {program} failed' )
            Data.Print( traceback.format_exc() )

        finally:
            HG.view_shutdown = True
            HG.model_shutdown = True
            
            try:
                controller.pubimmediate( 'wake_daemons' )
                
            except:
                Data.Print( traceback.format_exc() )
                
            reactor.callFromThread( reactor.stop )
            Data.Print( f'hydrus {program} shut down' )

    HG.shutdown_complete = True
    
    if HG.restart:
        Data.RestartProcess()

def SetupDirectories():
    db_dir = HC.DEFAULT_DB_DIR if result.db_dir is None else db_dir = result.db_dir
        
    if not Paths.DirectoryIsWritable( db_dir ) or HC.RUNNING_FROM_OSX_APP:
        db_dir = HC.USERPATH_DB_DIR
    
    db_dir = Paths.ConvertPortablePathToAbsPath( db_dir, HC.BASE_DIR )

    try:
        Paths.MakeSureDirectoryExists( db_dir )
    except:
        raise Exception( 'Could not ensure db path ' + db_dir + ' exists! Check the location is correct and that you have permission to write to it!' )
    
    if result.temp_dir is not None:
        if not os.path.exists( result.temp_dir ):
            raise Exception( 'The given temp directory, "{}", does not exist!'.format( result.temp_dir ) )
            
        if HC.PLATFORM_WINDOWS:
            os.environ[ 'TEMP' ] = result.temp_dir
            os.environ[ 'TMP' ] = result.temp_dir
            
        else:
            os.environ[ 'TMPDIR' ] = result.temp_dir

    return db_dir

def SetupArgParser():
    argparser = argparse.ArgumentParser( description = 'hydrus network launcher', usage = '%(prog)s client|server [OPTIONS]')
    
    argsubparsers = argparser.add_subparsers( dest = 'program' )

    clientparser = argsubparsers.add_parser( 'client', help = 'client help' )
    
    serverparser = argsubparsers.add_parser( 'server', help = 'server help' )
    serverparser.add_argument( 'action', default = 'start', nargs = '?', choices = [ 'start', 'stop', 'restart' ], help = 'either start this server (default), or stop an existing server, or both' )
    
    argparser.add_argument( '-d', '--db_dir', help = 'set an external db location' )
    argparser.add_argument( '--no_daemons', action='store_true', help = 'run without background daemons' )
    argparser.add_argument( '--no_wal', action='store_true', help = 'run without WAL db journalling' )
    argparser.add_argument( '--no_db_temp_files', action='store_true', help = 'run the db entirely in memory' )
    argparser.add_argument( '--temp_dir', help = 'override the program\'s temporary directory' )
    
    return argparser.parse_args()