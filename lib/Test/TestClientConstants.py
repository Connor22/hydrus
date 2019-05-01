### IMPORTS ###
from lib.Client import Constants as CC, Networking, Caches, Services

from lib.ClientGUI import Management

from lib.Hydrus import Constants as HC, Data, Globals as HG

import collections, os, unittest

### CODE ###
class TestManagers( unittest.TestCase ):
    
    def test_services( self ):
        
        def test_service( service, key, service_type, name ):
            
            self.assertEqual( service.GetServiceKey(), key )
            self.assertEqual( service.GetServiceType(), service_type )
            self.assertEqual( service.GetName(), name )
            
        
        repo_key = Data.GenerateKey()
        repo_type = HC.TAG_REPOSITORY
        repo_name = 'test tag repo'
        
        repo = Services.GenerateService( repo_key, repo_type, repo_name )
        
        other_key = Data.GenerateKey()
        
        other = Services.GenerateService( other_key, HC.LOCAL_BOORU, 'booru' )
        
        services = []
        
        services.append( repo )
        services.append( other )
        
        HG.test_controller.SetRead( 'services', services )
        
        services_manager = Caches.ServicesManager( HG.client_controller )
        
        #
        
        service = services_manager.GetService( repo_key )
        
        test_service( service, repo_key, repo_type, repo_name )
        
        service = services_manager.GetService( other_key )
        
        #
        
        services = services_manager.GetServices( ( HC.TAG_REPOSITORY, ) )
        
        self.assertEqual( len( services ), 1 )
        
        self.assertEqual( services[0].GetServiceKey(), repo_key )
        
        #
        
        services = []
        
        services.append( repo )
        
        HG.test_controller.SetRead( 'services', services )
        
        services_manager.RefreshServices()
        
        self.assertRaises( Exception, services_manager.GetService, other_key )
        
    
    def test_undo( self ):
        
        hash_1 = Data.GenerateKey()
        hash_2 = Data.GenerateKey()
        hash_3 = Data.GenerateKey()
        
        command_1 = { CC.COMBINED_LOCAL_FILE_SERVICE_KEY : [ Data.ContentUpdate( HC.CONTENT_TYPE_FILES, HC.CONTENT_UPDATE_ARCHIVE, { hash_1 } ) ] }
        command_2 = { CC.COMBINED_LOCAL_FILE_SERVICE_KEY : [ Data.ContentUpdate( HC.CONTENT_TYPE_FILES, HC.CONTENT_UPDATE_INBOX, { hash_2 } ) ] }
        command_3 = { CC.COMBINED_LOCAL_FILE_SERVICE_KEY : [ Data.ContentUpdate( HC.CONTENT_TYPE_FILES, HC.CONTENT_UPDATE_ARCHIVE, { hash_1, hash_3 } ) ] }
        
        command_1_inverted = { CC.COMBINED_LOCAL_FILE_SERVICE_KEY : [ Data.ContentUpdate( HC.CONTENT_TYPE_FILES, HC.CONTENT_UPDATE_INBOX, { hash_1 } ) ] }
        command_2_inverted = { CC.COMBINED_LOCAL_FILE_SERVICE_KEY : [ Data.ContentUpdate( HC.CONTENT_TYPE_FILES, HC.CONTENT_UPDATE_ARCHIVE, { hash_2 } ) ] }
        
        undo_manager = Caches.UndoManager( HG.client_controller )
        
        #
        
        HG.test_controller.ClearWrites( 'content_updates' )
        
        undo_manager.AddCommand( 'content_updates', command_1 )
        
        self.assertEqual( ( 'undo archive 1 files', None ), undo_manager.GetUndoRedoStrings() )
        
        undo_manager.AddCommand( 'content_updates', command_2 )
        
        self.assertEqual( ( 'undo inbox 1 files', None ), undo_manager.GetUndoRedoStrings() )
        
        undo_manager.Undo()
        
        self.assertEqual( ( 'undo archive 1 files', 'redo inbox 1 files' ), undo_manager.GetUndoRedoStrings() )
        
        self.assertEqual( HG.test_controller.GetWrite( 'content_updates' ), [ ( ( command_2_inverted, ), {} ) ] )
        
        undo_manager.Redo()
        
        self.assertEqual( HG.test_controller.GetWrite( 'content_updates' ), [ ( ( command_2, ), {} ) ] )
        
        self.assertEqual( ( 'undo inbox 1 files', None ), undo_manager.GetUndoRedoStrings() )
        
        undo_manager.Undo()
        
        self.assertEqual( HG.test_controller.GetWrite( 'content_updates' ), [ ( ( command_2_inverted, ), {} ) ] )
        
        undo_manager.Undo()
        
        self.assertEqual( HG.test_controller.GetWrite( 'content_updates' ), [ ( ( command_1_inverted, ), {} ) ] )
        
        self.assertEqual( ( None, 'redo archive 1 files' ), undo_manager.GetUndoRedoStrings() )
        
        undo_manager.AddCommand( 'content_updates', command_3 )
        
        self.assertEqual( ( 'undo archive 2 files', None ), undo_manager.GetUndoRedoStrings() )
        
    
