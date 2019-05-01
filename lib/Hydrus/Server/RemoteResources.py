from lib.Hydrus import Constants as HC, Exceptions, Network, Networking, Paths, Serialisable, Data, Globals as HG
from lib.Hydrus.Handling import FileHandling, ImageHandling

from lib.Server import Files

import os, time, traceback
import http.cookies

from twisted.internet import reactor, defer
from twisted.internet.threads import deferToThread

from twisted.web.server import NOT_DONE_YET
from twisted.web.resource import Resource
from twisted.web.static import File as FileResource, NoRangeStaticProducer
  
hydrus_favicon = FileResource( os.path.join( HC.STATIC_DIR, 'hydrus.ico' ), defaultType = 'image/x-icon' )

### CLASSES ###
class HydrusDomain( object ):
    def __init__( self, local_only ):
        self._local_only = local_only
    

    def CheckValid( self, client_ip ):
        if self._local_only and client_ip != '127.0.0.1':
            raise Exceptions.InsufficientCredentialsException( 'Only local access allowed!' )
    

    def IsLocal( self ):
        return self._local_only
   


class HydrusResource( Resource ):
    def __init__( self, service, domain ):
        Resource.__init__( self )
        
        self._service = service
        self._service_key = self._service.GetServiceKey()
        self._domain = domain
        
        service_type = self._service.GetServiceType()
        
        self._server_version_string = HC.service_string_lookup[ service_type ] + '/' + str( HC.NETWORK_VERSION )
    

    def _callbackCheckRestrictions( self, request ):
        self._domain.CheckValid( request.getClientIP() )
        
        self._checkService( request )
        
        self._checkUserAgent( request )
        
        return request
        
    
    def _callbackParseGETArgs( self, request ):
        return request
        
    
    def _callbackParsePOSTArgs( self, request ):
        return request
        
    
    def _checkService( self, request ):
        if HG.server_busy:
            raise Exceptions.ServerBusyException( 'This server is busy, please try again later.' )
        
        return request
        
    
    def _checkUserAgent( self, request ):
        request.is_hydrus_user_agent = False
        
        if request.requestHeaders.hasHeader( 'User-Agent' ):
            user_agent_texts = request.requestHeaders.getRawHeaders( 'User-Agent' )
            
            user_agent_text = user_agent_texts[0]
            
            try:
                user_agents = user_agent_text.split( ' ' )
                
            except:
                return # crazy user agent string, so just assume not a hydrus client
                
            for user_agent in user_agents:
                if '/' in user_agent:
                    ( client, network_version ) = user_agent.split( '/', 1 )
                    
                    if client == 'hydrus':
                        request.is_hydrus_user_agent = True
                        
                        network_version = int( network_version )
                        
                        if network_version == HC.NETWORK_VERSION:
                            return
                            
                        else:
                            if network_version < HC.NETWORK_VERSION: message = 'Your client is out of date; please download the latest release.'
                            else: message = 'This server is out of date; please ask its admin to update to the latest release.'
                            raise Exceptions.NetworkVersionException( 'Network version mismatch! This server\'s network version is ' + str( HC.NETWORK_VERSION ) + ', whereas your client\'s is ' + str( network_version ) + '! ' + message )
    

    def _callbackRenderResponseContext( self, request ):
        self._CleanUpTempFile( request )
        
        if request.channel is None:
            # Connection was lost, it seems.
            request.finish()
            
            return
            
        response_context = request.hydrus_response_context
        status_code = response_context.GetStatusCode()
        request.setResponseCode( status_code )
        
        for ( k, v, kwargs ) in response_context.GetCookies():
            request.addCookie( k, v, **kwargs )
        
        do_finish = True
        
        if response_context.HasPath():
            path = response_context.GetPath()
            size = os.path.getsize( path )
            mime = response_context.GetMime()
            
            content_type = HC.mime_string_lookup[ mime ]
            content_length = size
            
            ( base, filename ) = os.path.split( path )
            content_disposition = 'inline; filename="' + filename + '"'
            
            request.setHeader( 'Content-Type', str( content_type ) )
            request.setHeader( 'Content-Length', str( content_length ) )
            request.setHeader( 'Content-Disposition', str( content_disposition ) )
            request.setHeader( 'Expires', time.strftime( '%a, %d %b %Y %H:%M:%S GMT', time.gmtime( time.time() + 86400 * 365 ) ) )
            request.setHeader( 'Cache-Control', 'max-age={}'.format( 86400 * 365 ) )
            
            fileObject = open( path, 'rb' )
            
            producer = NoRangeStaticProducer( request, fileObject )
            producer.start()
            
            do_finish = False
            
        elif response_context.HasBody():
            mime = response_context.GetMime()
            body_bytes = response_context.GetBodyBytes()
            
            content_type = HC.mime_string_lookup[ mime ]
            content_length = len( body_bytes )
            content_disposition = 'inline'
            
            request.setHeader( 'Content-Type', content_type )
            request.setHeader( 'Content-Length', str( content_length ) )
            request.setHeader( 'Content-Disposition', content_disposition )
            
            request.write( body_bytes )
            
        else:
            content_length = 0
            
            if status_code != 204: # 204 is No Content
                request.setHeader( 'Content-Length', str( content_length ) )
        
        self._reportDataUsed( request, content_length )
        self._reportRequestUsed( request )
        
        if do_finish:
            request.finish()
        
    
    def _callbackDoGETJob( self, request ):
        def wrap_thread_result( response_context ):
            request.hydrus_response_context = response_context
            
            return request
        
        d = deferToThread( self._threadDoGETJob, request )
        d.addCallback( wrap_thread_result )
        
        return d
        
    
    def _callbackDoOPTIONSJob( self, request ):
        def wrap_thread_result( response_context ):
            request.hydrus_response_context = response_context
            
            return request
        
        d = deferToThread( self._threadDoOPTIONSJob, request )
        
        d.addCallback( wrap_thread_result )
        
        return d
        
    
    def _callbackDoPOSTJob( self, request ):
        def wrap_thread_result( response_context ):
            request.hydrus_response_context = response_context
            
            return request
            
        
        d = deferToThread( self._threadDoPOSTJob, request )
        
        d.addCallback( wrap_thread_result )
        
        return d
        
    
    def _DecompressionBombsOK( self, request ):
        return False
        
    
    def _errbackDisconnected( self, failure, request_deferred ):
        request_deferred.cancel()
        
    
    def _errbackHandleEmergencyError( self, failure, request ):
        try: self._CleanUpTempFile( request )
        except: pass
        
        try: Data.DebugPrint( failure.getTraceback() )
        except: pass
        
        if request.channel is not None:
            try: request.setResponseCode( 500 )
            except: pass
            
            try: request.write( failure.getTraceback() )
            except: pass
        
        if not request.finished:
            try: request.finish()
            except: pass
        
    
    def _errbackHandleProcessingError( self, failure, request ):
        self._CleanUpTempFile( request )
        
        default_mime = HC.TEXT_HTML
        default_encoding = str
        
        if failure.type == Exceptions.BadRequestException:
            response_context = ResponseContext( 400, mime = default_mime, body = default_encoding( failure.value ) )
            
        elif failure.type in ( Exceptions.MissingCredentialsException, Exceptions.DoesNotSupportCORSException ):
            response_context = ResponseContext( 401, mime = default_mime, body = default_encoding( failure.value ) )
            
        elif failure.type == Exceptions.InsufficientCredentialsException:
            response_context = ResponseContext( 403, mime = default_mime, body = default_encoding( failure.value ) )
            
        elif failure.type in ( Exceptions.NotFoundException, Exceptions.DataMissing, Exceptions.FileMissingException ):
            response_context = ResponseContext( 404, mime = default_mime, body = default_encoding( failure.value ) )
            
        elif failure.type == Exceptions.SessionException:
            response_context = ResponseContext( 419, mime = default_mime, body = default_encoding( failure.value ) )
            
        elif failure.type == Exceptions.NetworkVersionException:
            response_context = ResponseContext( 426, mime = default_mime, body = default_encoding( failure.value ) )
            
        elif failure.type == Exceptions.ServerBusyException:
            response_context = ResponseContext( 503, mime = default_mime, body = default_encoding( failure.value ) )
            
        elif failure.type == Exceptions.BandwidthException:
            response_context = ResponseContext( 509, mime = default_mime, body = default_encoding( failure.value ) )
            
        else:
            Data.DebugPrint( failure.getTraceback() )
            response_context = ResponseContext( 500, mime = default_mime, body = default_encoding( 'The repository encountered an error it could not handle! Here is a dump of what happened, which will also be written to your client.log file. If it persists, please forward it to hydrus.admin@gmail.com:' + os.linesep * 2 + failure.getTraceback() ) )
            
        request.hydrus_response_context = response_context
        
        return request
        
    
    def _parseHydrusNetworkAccessKey( self, request ):
        if not request.requestHeaders.hasHeader( 'Hydrus-Key' ):
            raise Exceptions.MissingCredentialsException( 'No hydrus key header found!' )
        
        hex_keys = request.requestHeaders.getRawHeaders( 'Hydrus-Key' )
        
        hex_key = hex_keys[0]
        
        try:
            access_key = bytes.fromhex( hex_key )
            
        except:
            raise Exceptions.InsufficientCredentialsException( 'Could not parse the hydrus key!' )
        
        return access_key
        
    
    def _reportDataUsed( self, request, num_bytes ):
        self._service.ReportDataUsed( num_bytes )
        
        HG.controller.ReportDataUsed( num_bytes )
        
    
    def _reportRequestUsed( self, request ):
        self._service.ReportRequestUsed()
        
        HG.controller.ReportRequestUsed()
        
    
    def _threadDoGETJob( self, request ):
        raise Exceptions.NotFoundException( 'This service does not support that request!' )
        
    
    def _threadDoOPTIONSJob( self, request ):
        allowed_methods = []
        
        if self._threadDoGETJob.__func__ != Resource._threadDoGETJob:
            allowed_methods.append( 'GET' )
            
        if self._threadDoPOSTJob.__func__ != Resource._threadDoPOSTJob:
            allowed_methods.append( 'POST' )
        
        allowed_methods_string = ', '.join( allowed_methods )
        
        if request.requestHeaders.hasHeader( 'Origin' ):
            # this is a CORS request
            if self._service.SupportsCORS():
                request.setHeader( 'Access-Control-Allow-Origin', '*' )
                request.setHeader( 'Access-Control-Allow-Methods', allowed_methods_string )
                
            else:
                # 401
                raise Exceptions.DoesNotSupportCORSException( 'This service does not support CORS.' )
            
        else:
            # regular OPTIONS request
            request.setHeader( 'Allow', allowed_methods_string )
        
        # 204 No Content
        response_context = ResponseContext( 204 )
        
        return response_context
        
    
    def _threadDoPOSTJob( self, request ):
        raise Exceptions.NotFoundException( 'This service does not support that request!' )
        
    
    def _CleanUpTempFile( self, request ):
        if hasattr( request, 'temp_file_info' ):
            ( os_file_handle, temp_path ) = request.temp_file_info
            
            Paths.CleanUpTempPath( os_file_handle, temp_path )
            
            del request.temp_file_info
            
        
    
    def render_GET( self, request ):
        request.setHeader( 'Server', self._server_version_string )
        
        d = defer.Deferred()
        
        d.addCallback( self._callbackCheckRestrictions )
        
        d.addCallback( self._callbackParseGETArgs )
        
        d.addCallback( self._callbackDoGETJob )
        
        d.addErrback( self._errbackHandleProcessingError, request )
        
        d.addCallback( self._callbackRenderResponseContext )
        
        d.addErrback( self._errbackHandleEmergencyError, request )
        
        reactor.callLater( 0, d.callback, request )
        
        request.notifyFinish().addErrback( self._errbackDisconnected, d )
        
        return NOT_DONE_YET
        
    
    def render_OPTIONS( self, request ):
        request.setHeader( 'Server', self._server_version_string )
        
        d = defer.Deferred()
        
        d.addCallback( self._callbackCheckRestrictions )
        
        d.addCallback( self._callbackDoOPTIONSJob )
        
        d.addErrback( self._errbackHandleProcessingError, request )
        
        d.addCallback( self._callbackRenderResponseContext )
        
        d.addErrback( self._errbackHandleEmergencyError, request )
        
        reactor.callLater( 0, d.callback, request )
        
        request.notifyFinish().addErrback( self._errbackDisconnected, d )
        
        return NOT_DONE_YET
        
    
    def render_POST( self, request ):
        request.setHeader( 'Server', self._server_version_string )
        
        d = defer.Deferred()
        
        d.addCallback( self._callbackCheckRestrictions )
        
        d.addCallback( self._callbackParsePOSTArgs )
        
        d.addCallback( self._callbackDoPOSTJob )
        
        d.addErrback( self._errbackHandleProcessingError, request )
        
        d.addCallback( self._callbackRenderResponseContext )
        
        d.addErrback( self._errbackHandleEmergencyError, request )
        
        reactor.callLater( 0, d.callback, request )
        
        request.notifyFinish().addErrback( self._errbackDisconnected, d )
        
        return NOT_DONE_YET
        

    
class HydrusResourceRobotsTXT( Resource ):
    def _threadDoGETJob( self, request ):
        body = '''User-agent: *
Disallow: /'''
        
        response_context = ResponseContext( 200, mime = HC.TEXT_PLAIN, body = body )
        
        return response_context
        

    
class HydrusResourceWelcome( Resource ):
    def _threadDoGETJob( self, request ):
        body = GenerateEris( self._service )
        
        response_context = ResponseContext( 200, mime = HC.TEXT_HTML, body = body )
        
        return response_context
        
    

class ResponseContext( object ):
    def __init__( self, status_code, mime = HC.APPLICATION_JSON, body = None, path = None, cookies = None ):
        if body is None:
            body_bytes = None
            
        elif isinstance( body, Serialisable.SerialisableBase ):
            body_bytes = body.DumpToNetworkBytes()
            
        elif isinstance( body, str ):
            body_bytes = bytes( body, 'utf-8' )
            
        elif isinstance( body, bytes ):
            body_bytes = body
            
        else:
            raise Exception( 'Was given an incompatible object to respond with: ' + repr( body ) )
                
        if cookies is None:
            cookies = []
        
        self._status_code = status_code
        self._mime = mime
        self._body_bytes = body_bytes
        self._path = path
        self._cookies = cookies
        
    
    def GetBodyBytes( self ): return self._body_bytes
        

    def GetCookies( self ): return self._cookies
    

    def GetMime( self ): return self._mime
    

    def GetPath( self ): return self._path
    

    def GetStatusCode( self ): return self._status_code
    

    def HasBody( self ): return self._body_bytes is not None
    

    def HasPath( self ): return self._path is not None
    

### FUNCTIONS ###
def ParseFileArguments( path, decompression_bombs_ok = False ):
    ImageHandling.ConvertToPngIfBmp( path )
    
    hash = FileHandling.GetHashFromPath( path )
    
    try:
        mime = FileHandling.GetMime( path )
        
        if mime in HC.DECOMPRESSION_BOMB_IMAGES and not decompression_bombs_ok:
            if ImageHandling.IsDecompressionBomb( path ):
                raise Exceptions.InsufficientCredentialsException( 'File seemed to be a Decompression Bomb!' )
                
        ( size, mime, width, height, duration, num_frames, num_words ) = FileHandling.GetFileInfo( path, mime )
        
    except Exception as e:
        raise Exceptions.BadRequestException( 'File ' + hash.hex() + ' could not parse: ' + str( e ) )
    
    args = Networking.ParsedRequestArguments()
    
    args[ 'path' ] = path
    args[ 'hash' ] = hash
    args[ 'size' ] = size
    args[ 'mime' ] = mime
    
    if width is not None: args[ 'width' ] = width
    if height is not None: args[ 'height' ] = height
    if duration is not None: args[ 'duration' ] = duration
    if num_frames is not None: args[ 'num_frames' ] = num_frames
    if num_words is not None: args[ 'num_words' ] = num_words
    
    if mime in HC.MIMES_WITH_THUMBNAILS:
        try:
            bounding_dimensions = HC.SERVER_THUMBNAIL_DIMENSIONS
            
            thumbnail_bytes = FileHandling.GenerateThumbnailBytes( path, bounding_dimensions, mime, width, height, duration, num_frames )
            
        except Exception as e:
            tb = traceback.format_exc()
            
            raise Exceptions.BadRequestException( 'Could not generate thumbnail from that file:' + os.linesep + tb )
            
        args[ 'thumbnail' ] = thumbnail_bytes
    
    return args
  

def GenerateEris( service ):
    name = service.GetName()
    service_type = service.GetServiceType()
    
    allows_non_local_connections = service.AllowsNonLocalConnections()
    
    welcome_text_1 = 'This is <b>' + name + '</b>,'
    welcome_text_2 = 'a ' + HC.service_string_lookup[ service_type ] + '.'
    welcome_text_3 = 'Software version ' + str( HC.SOFTWARE_VERSION )
    
    if service_type == HC.CLIENT_API_SERVICE:
        welcome_text_4 = 'API version ' + str( HC.CLIENT_API_VERSION )
        
    else:
        welcome_text_4 = 'Network version ' + str( HC.NETWORK_VERSION )
    
    if allows_non_local_connections:
        welcome_text_5 = 'It responds to requests from any host.'
        
    else:
        welcome_text_5 = 'It only responds to requests from localhost.'
    
    return '''<html><head><title>''' + name + '''</title></head><body><pre>
                         <font color="red">8888  8888888</font>
                  <font color="red">888888888888888888888888</font>
               <font color="red">8888</font>:::<font color="red">8888888888888888888888888</font>
             <font color="red">8888</font>::::::<font color="red">8888888888888888888888888888</font>
            <font color="red">88</font>::::::::<font color="red">888</font>:::<font color="red">8888888888888888888888888</font>
          <font color="red">88888888</font>::::<font color="red">8</font>:::::::::::<font color="red">88888888888888888888</font>
        <font color="red">888 8</font>::<font color="red">888888</font>::::::::::::::::::<font color="red">88888888888   888</font>
           <font color="red">88</font>::::<font color="red">88888888</font>::::<font color="gray">m</font>::::::::::<font color="red">88888888888    8</font>
         <font color="red">888888888888888888</font>:<font color="gray">M</font>:::::::::::<font color="red">8888888888888</font>
        <font color="red">88888888888888888888</font>::::::::::::<font color="gray">M</font><font color="red">88888888888888</font>
        <font color="red">8888888888888888888888</font>:::::::::<font color="gray">M</font><font color="red">8888888888888888</font>
         <font color="red">8888888888888888888888</font>:::::::<font color="gray">M</font><font color="red">888888888888888888</font>
        <font color="red">8888888888888888</font>::<font color="red">88888</font>::::::<font color="gray">M</font><font color="red">88888888888888888888</font>
      <font color="red">88888888888888888</font>:::<font color="red">88888</font>:::::<font color="gray">M</font><font color="red">888888888888888   8888</font>
     <font color="red">88888888888888888</font>:::<font color="red">88888</font>::::<font color="gray">M</font>::<font color="black">;o</font><font color="maroon">*</font><font color="green">M</font><font color="maroon">*</font><font color="black">o;</font><font color="red">888888888    88</font>
    <font color="red">88888888888888888</font>:::<font color="red">8888</font>:::::<font color="gray">M</font>:::::::::::<font color="red">88888888    8</font>
   <font color="red">88888888888888888</font>::::<font color="red">88</font>::::::<font color="gray">M</font>:<font color="gray">;</font>:::::::::::<font color="red">888888888</font>
  <font color="red">8888888888888888888</font>:::<font color="red">8</font>::::::<font color="gray">M</font>::<font color="gray">aAa</font>::::::::<font color="gray">M</font><font color="red">8888888888       8</font>
  <font color="red">88   8888888888</font>::<font color="red">88</font>::::<font color="red">8</font>::::<font color="gray">M</font>:::::::::::::<font color="red">888888888888888 8888</font>
 <font color="red">88  88888888888</font>:::<font color="red">8</font>:::::::::<font color="gray">M</font>::::::::::;::<font color="red">88</font><font color="black">:</font><font color="red">88888888888888888</font>
 <font color="red">8  8888888888888</font>:::::::::::<font color="gray">M</font>::<font color="violet">&quot;@@@@@@@&quot;</font>::::<font color="red">8</font><font color="gray">w</font><font color="red">8888888888888888</font>
  <font color="red">88888888888</font>:<font color="red">888</font>::::::::::<font color="gray">M</font>:::::<font color="violet">&quot;@a@&quot;</font>:::::<font color="gray">M</font><font color="red">8</font><font color="gray">i</font><font color="red">888888888888888</font>
 <font color="red">8888888888</font>::::<font color="red">88</font>:::::::::<font color="gray">M</font><font color="red">88</font>:::::::::::::<font color="gray">M</font><font color="red">88</font><font color="gray">z</font><font color="red">88888888888888888</font>
<font color="red">8888888888</font>:::::<font color="red">8</font>:::::::::<font color="gray">M</font><font color="red">88888</font>:::::::::<font color="gray">MM</font><font color="red">888</font><font color="gray">!</font><font color="red">888888888888888888</font>
<font color="red">888888888</font>:::::<font color="red">8</font>:::::::::<font color="gray">M</font><font color="red">8888888</font><font color="gray">MAmmmAMVMM</font><font color="red">888</font><font color="gray">*</font><font color="red">88888888   88888888</font>
<font color="red">888888</font> <font color="gray">M</font>:::::::::::::::<font color="gray">M</font><font color="red">888888888</font>:::::::<font color="gray">MM</font><font color="red">88888888888888   8888888</font>
<font color="red">8888</font>   <font color="gray">M</font>::::::::::::::<font color="gray">M</font><font color="red">88888888888</font>::::::<font color="gray">MM</font><font color="red">888888888888888    88888</font>
 <font color="red">888</font>   <font color="gray">M</font>:::::::::::::<font color="gray">M</font><font color="red">8888888888888</font><font color="gray">M</font>:::::<font color="gray">mM</font><font color="red">888888888888888    8888</font>
  <font color="red">888</font>  <font color="gray">M</font>::::::::::::<font color="gray">M</font><font color="red">8888</font>:<font color="red">888888888888</font>::::<font color="gray">m</font>::<font color="gray">Mm</font><font color="red">88888 888888   8888</font>
   <font color="red">88</font>  <font color="gray">M</font>::::::::::::<font color="red">8888</font>:<font color="red">88888888888888888</font>::::::<font color="gray">Mm</font><font color="red">8   88888   888</font>
   <font color="red">88</font>  <font color="gray">M</font>::::::::::<font color="red">8888</font><font color="gray">M</font>::<font color="red">88888</font>::<font color="red">888888888888</font>:::::::<font color="gray">Mm</font><font color="red">88888    88</font>
   <font color="red">8</font>   <font color="gray">MM</font>::::::::<font color="red">8888</font><font color="gray">M</font>:::<font color="red">8888</font>:::::<font color="red">888888888888</font>::::::::<font color="gray">Mm</font><font color="red">8     4</font>              ''' + welcome_text_1 + '''
       <font color="red">8</font><font color="gray">M</font>:::::::<font color="red">8888</font><font color="gray">M</font>:::::<font color="red">888</font>:::::::<font color="red">88</font>:::<font color="red">8888888</font>::::::::<font color="gray">Mm</font>    <font color="red">2</font>              ''' + welcome_text_2 + '''
      <font color="red">88</font><font color="gray">MM</font>:::::<font color="red">8888</font><font color="gray">M</font>:::::::<font color="red">88</font>::::::::<font color="red">8</font>:::::<font color="red">888888</font>:::<font color="gray">M</font>:::::<font color="gray">M</font>
     <font color="red">8888</font><font color="gray">M</font>:::::<font color="red">888</font><font color="gray">MM</font>::::::::<font color="red">8</font>:::::::::::<font color="gray">M</font>::::<font color="red">8888</font>::::<font color="gray">M</font>::::<font color="gray">M</font>                  ''' + welcome_text_3 + '''
    <font color="red">88888</font><font color="gray">M</font>:::::<font color="red">88</font>:<font color="gray">M</font>::::::::::<font color="red">8</font>:::::::::::<font color="gray">M</font>:::<font color="red">8888</font>::::::<font color="gray">M</font>::<font color="gray">M</font>                  ''' + welcome_text_4 + '''
   <font color="red">88 888</font><font color="gray">MM</font>:::<font color="red">888</font>:<font color="gray">M</font>:::::::::::::::::::::::<font color="gray">M</font>:<font color="red">8888</font>:::::::::<font color="gray">M</font>:
   <font color="red">8 88888</font><font color="gray">M</font>:::<font color="red">88</font>::<font color="gray">M</font>:::::::::::::::::::::::<font color="gray">MM</font>:<font color="red">88</font>::::::::::::<font color="gray">M</font>                 ''' + welcome_text_5 + '''
     <font color="red">88888</font><font color="gray">M</font>:::<font color="red">88</font>::<font color="gray">M</font>::::::::::<font color="thistle">*88*</font>::::::::::<font color="gray">M</font>:<font color="red">88</font>::::::::::::::<font color="gray">M</font>
    <font color="red">888888</font><font color="gray">M</font>:::<font color="red">88</font>::<font color="gray">M</font>:::::::::<font color="thistle">88@@88</font>:::::::::<font color="gray">M</font>::<font color="red">88</font>::::::::::::::<font color="gray">M</font>
    <font color="red">888888</font><font color="gray">MM</font>::<font color="red">88</font>::<font color="gray">MM</font>::::::::<font color="thistle">88@@88</font>:::::::::<font color="gray">M</font>:::<font color="red">8</font>::::::::::::::<font color="thistle">*8</font>
    <font color="red">88888</font>  <font color="gray">M</font>:::<font color="red">8</font>::<font color="gray">MM</font>:::::::::<font color="thistle">*88*</font>::::::::::<font color="gray">M</font>:::::::::::::::::<font color="thistle">88@@</font>
    <font color="red">8888</font>   <font color="gray">MM</font>::::::<font color="gray">MM</font>:::::::::::::::::::::<font color="gray">MM</font>:::::::::::::::::<font color="thistle">88@@</font>
     <font color="red">888</font>    <font color="gray">M</font>:::::::<font color="gray">MM</font>:::::::::::::::::::<font color="gray">MM</font>::<font color="gray">M</font>::::::::::::::::<font color="thistle">*8</font>
     <font color="red">888</font>    <font color="gray">MM</font>:::::::<font color="gray">MMM</font>::::::::::::::::<font color="gray">MM</font>:::<font color="gray">MM</font>:::::::::::::::<font color="gray">M</font>
      <font color="red">88</font>     <font color="gray">M</font>::::::::<font color="gray">MMMM</font>:::::::::::<font color="gray">MMMM</font>:::::<font color="gray">MM</font>::::::::::::<font color="gray">MM</font>
       <font color="red">88</font>    <font color="gray">MM</font>:::::::::<font color="gray">MMMMMMMMMMMMMMM</font>::::::::<font color="gray">MMM</font>::::::::<font color="gray">MMM</font>
        <font color="red">88</font>    <font color="gray">MM</font>::::::::::::<font color="gray">MMMMMMM</font>::::::::::::::<font color="gray">MMMMMMMMMM</font>
         <font color="red">88   8</font><font color="gray">MM</font>::::::::::::::::::::::::::::::::::<font color="gray">MMMMMM</font>
          <font color="red">8   88</font><font color="gray">MM</font>::::::::::::::::::::::<font color="gray">M</font>:::<font color="gray">M</font>::::::::<font color="gray">MM</font>
              <font color="red">888</font><font color="gray">MM</font>::::::::::::::::::<font color="gray">MM</font>::::::<font color="gray">MM</font>::::::<font color="gray">MM</font>
             <font color="red">88888</font><font color="gray">MM</font>:::::::::::::::<font color="gray">MMM</font>:::::::<font color="gray">mM</font>:::::<font color="gray">MM</font>
             <font color="red">888888</font><font color="gray">MM</font>:::::::::::::<font color="gray">MMM</font>:::::::::<font color="gray">MMM</font>:::<font color="gray">M</font>
            <font color="red">88888888</font><font color="gray">MM</font>:::::::::::<font color="gray">MMM</font>:::::::::::<font color="gray">MM</font>:::<font color="gray">M</font>
           <font color="red">88 8888888</font><font color="gray">M</font>:::::::::<font color="gray">MMM</font>::::::::::::::<font color="gray">M</font>:::<font color="gray">M</font>
           <font color="red">8  888888</font> <font color="gray">M</font>:::::::<font color="gray">MM</font>:::::::::::::::::<font color="gray">M</font>:::<font color="gray">M</font>:
              <font color="red">888888</font> <font color="gray">M</font>::::::<font color="gray">M</font>:::::::::::::::::::<font color="gray">M</font>:::<font color="gray">MM</font>
             <font color="red">888888</font>  <font color="gray">M</font>:::::<font color="gray">M</font>::::::::::::::::::::::::<font color="gray">M</font>:<font color="gray">M</font>
             <font color="red">888888</font>  <font color="gray">M</font>:::::<font color="gray">M</font>:::::::::<font color="gray">@</font>::::::::::::::<font color="gray">M</font>::<font color="gray">M</font>
             <font color="red">88888</font>   <font color="gray">M</font>::::::::::::::<font color="gray">@@</font>:::::::::::::::<font color="gray">M</font>::<font color="gray">M</font>
            <font color="red">88888</font>   <font color="gray">M</font>::::::::::::::<font color="gray">@@@</font>::::::::::::::::<font color="gray">M</font>::<font color="gray">M</font>
           <font color="red">88888</font>   <font color="gray">M</font>:::::::::::::::<font color="gray">@@</font>::::::::::::::::::<font color="gray">M</font>::<font color="gray">M</font>
          <font color="red">88888</font>   <font color="gray">M</font>:::::<font color="gray">m</font>::::::::::<font color="gray">@</font>::::::::::<font color="gray">Mm</font>:::::::<font color="gray">M</font>:::<font color="gray">M</font>
          <font color="red">8888</font>   <font color="gray">M</font>:::::<font color="gray">M</font>:::::::::::::::::::::::<font color="gray">MM</font>:::::::<font color="gray">M</font>:::<font color="gray">M</font>
         <font color="red">8888</font>   <font color="gray">M</font>:::::<font color="gray">M</font>:::::::::::::::::::::::<font color="gray">MMM</font>::::::::<font color="gray">M</font>:::<font color="gray">M</font>
        <font color="red">888</font>    <font color="gray">M</font>:::::<font color="gray">Mm</font>::::::::::::::::::::::<font color="gray">MMM</font>:::::::::<font color="gray">M</font>::::<font color="gray">M</font>
      <font color="red">8888</font>    <font color="gray">MM</font>::::<font color="gray">Mm</font>:::::::::::::::::::::<font color="gray">MMMM</font>:::::::::<font color="gray">m</font>::<font color="gray">m</font>:::<font color="gray">M</font>
     <font color="red">888</font>      <font color="gray">M</font>:::::<font color="gray">M</font>::::::::::::::::::::<font color="gray">MMM</font>::::::::::::<font color="gray">M</font>::<font color="gray">mm</font>:::<font color="gray">M</font>
  <font color="red">8888</font>       <font color="gray">MM</font>:::::::::::::::::::::::::<font color="gray">MM</font>:::::::::::::<font color="gray">mM</font>::<font color="gray">MM</font>:::<font color="gray">M</font>:
             <font color="gray">M</font>:::::::::::::::::::::::::<font color="gray">M</font>:::::::::::::::<font color="gray">mM</font>::<font color="gray">MM</font>:::<font color="gray">Mm</font>
            <font color="gray">MM</font>::::::<font color="gray">m</font>:::::::::::::::::::::::::::::::::::<font color="gray">M</font>::<font color="gray">MM</font>:::<font color="gray">MM</font>
            <font color="gray">M</font>::::::::<font color="gray">M</font>:::::::::::::::::::::::::::::::::::<font color="gray">M</font>::<font color="gray">M</font>:::<font color="gray">MM</font>
           <font color="gray">MM</font>:::::::::<font color="gray">M</font>:::::::::::::<font color="gray">M</font>:::::::::::::::::::::<font color="gray">M</font>:<font color="gray">M</font>:::<font color="gray">MM</font>
           <font color="gray">M</font>:::::::::::<font color="gray">M</font><font color="maroon">88</font>:::::::::<font color="gray">M</font>:::::::::::::::::::::::<font color="gray">MM</font>::<font color="gray">MMM</font> 
           <font color="gray">M</font>::::::::::::<font color="maroon">8888888888</font><font color="gray">M</font>::::::::::::::::::::::::<font color="gray">MM</font>::<font color="gray">MM</font> 
           <font color="gray">M</font>:::::::::::::<font color="maroon">88888888</font><font color="gray">M</font>:::::::::::::::::::::::::<font color="gray">M</font>::<font color="gray">MM</font>
           <font color="gray">M</font>::::::::::::::<font color="maroon">888888</font><font color="gray">M</font>:::::::::::::::::::::::::<font color="gray">M</font>::<font color="gray">MM</font>
           <font color="gray">M</font>:::::::::::::::<font color="maroon">88888</font><font color="gray">M</font>:::::::::::::::::::::::::<font color="gray">M</font>:<font color="gray">MM</font>
           <font color="gray">M</font>:::::::::::::::::<font color="maroon">88</font><font color="gray">M</font>::::::::::::::::::::::::::<font color="gray">MMM</font>
           <font color="gray">M</font>:::::::::::::::::::<font color="gray">M</font>::::::::::::::::::::::::::<font color="gray">MMM</font>
           <font color="gray">MM</font>:::::::::::::::::<font color="gray">M</font>::::::::::::::::::::::::::<font color="gray">MMM</font>
            <font color="gray">M</font>:::::::::::::::::<font color="gray">M</font>::::::::::::::::::::::::::<font color="gray">MMM</font>
            <font color="gray">MM</font>:::::::::::::::<font color="gray">M</font>::::::::::::::::::::::::::<font color="gray">MMM</font>
             <font color="gray">M</font>:::::::::::::::<font color="gray">M</font>:::::::::::::::::::::::::<font color="gray">MMM</font>
             <font color="gray">MM</font>:::::::::::::<font color="gray">M</font>:::::::::::::::::::::::::<font color="gray">MMM</font>
              <font color="gray">M</font>:::::::::::::<font color="gray">M</font>::::::::::::::::::::::::<font color="gray">MMM</font>
              <font color="gray">MM</font>:::::::::::<font color="gray">M</font>::::::::::::::::::::::::<font color="gray">MMM</font>
               <font color="gray">M</font>:::::::::::<font color="gray">M</font>:::::::::::::::::::::::<font color="gray">MMM</font>
               <font color="gray">MM</font>:::::::::<font color="gray">M</font>:::::::::::::::::::::::<font color="gray">MMM</font>
                <font color="gray">M</font>:::::::::<font color="gray">M</font>::::::::::::::::::::::<font color="gray">MMM</font>
                <font color="gray">MM</font>:::::::<font color="gray">M</font>::::::::::::::::::::::<font color="gray">MMM</font>
                 <font color="gray">MM</font>::::::<font color="gray">M</font>:::::::::::::::::::::<font color="gray">MMM</font>
                 <font color="gray">MM</font>:::::<font color="gray">M</font>:::::::::::::::::::::<font color="gray">MMM</font>
                  <font color="gray">MM</font>::::<font color="gray">M</font>::::::::::::::::::::<font color="gray">MMM</font> 
                  <font color="gray">MM</font>:::<font color="gray">M</font>::::::::::::::::::::<font color="gray">MMM</font>
                   <font color="gray">MM</font>::<font color="gray">M</font>:::::::::::::::::::<font color="gray">MMM</font>
                   <font color="gray">MM</font>:<font color="gray">M</font>:::::::::::::::::::<font color="gray">MMM</font>
                    <font color="gray">MMM</font>::::::::::::::::::<font color="gray">MMM</font>
                    <font color="gray">MM</font>::::::::::::::::::<font color="gray">MMM</font>
                     <font color="gray">M</font>:::::::::::::::::<font color="gray">MMM</font>
                    <font color="gray">MM</font>::::::::::::::::<font color="gray">MMM</font>
                    <font color="gray">MM</font>:::::::::::::::<font color="gray">MMM</font>
                    <font color="gray">MM</font>::::<font color="gray">M</font>:::::::::<font color="gray">MMM</font>:
                    <font color="gray">mMM</font>::::<font color="gray">MM</font>:::::::<font color="gray">MMMM</font>
                     <font color="gray">MMM</font>:::::::::::<font color="gray">MMM</font>:<font color="gray">M</font>
                     <font color="gray">mMM</font>:::<font color="gray">M</font>:::::::<font color="gray">M</font>:<font color="gray">M</font>:<font color="gray">M</font>
                      <font color="gray">MM</font>::<font color="gray">MMMM</font>:::::::<font color="gray">M</font>:<font color="gray">M</font>
                      <font color="gray">MM</font>::<font color="gray">MMM</font>::::::::<font color="gray">M</font>:<font color="gray">M</font>
                      <font color="gray">mMM</font>::<font color="gray">MM</font>::::::::<font color="gray">M</font>:<font color="gray">M</font>
                       <font color="gray">MM</font>::<font color="gray">MM</font>:::::::::<font color="gray">M</font>:<font color="gray">M</font>
                       <font color="gray">MM</font>::<font color="gray">MM</font>::::::::::<font color="gray">M</font>:<font color="gray">m</font>
                       <font color="gray">MM</font>:::<font color="gray">M</font>:::::::::::<font color="gray">MM</font>
                       <font color="gray">MMM</font>:::::::::::::::<font color="gray">M</font>:
                       <font color="gray">MMM</font>:::::::::::::::<font color="gray">M</font>:
                       <font color="gray">MMM</font>::::::::::::::::<font color="gray">M</font>
                       <font color="gray">MMM</font>::::::::::::::::<font color="gray">M</font>
                       <font color="gray">MMM</font>::::::::::::::::<font color="gray">Mm</font>
                        <font color="gray">MM</font>::::::::::::::::<font color="gray">MM</font>
                        <font color="gray">MMM</font>:::::::::::::::<font color="gray">MM</font>
                        <font color="gray">MMM</font>:::::::::::::::<font color="gray">MM</font>
                        <font color="gray">MMM</font>:::::::::::::::<font color="gray">MM</font>
                        <font color="gray">MMM</font>:::::::::::::::<font color="gray">MM</font>
                         <font color="gray">MM</font>::::::::::::::<font color="gray">MMM</font>
                         <font color="gray">MMM</font>:::::::::::::<font color="gray">MM</font>
                         <font color="gray">MMM</font>:::::::::::::<font color="gray">MM</font>
                         <font color="gray">MMM</font>::::::::::::<font color="gray">MM</font>
                          <font color="gray">MM</font>::::::::::::<font color="gray">MM</font>
                          <font color="gray">MM</font>::::::::::::<font color="gray">MM</font>
                          <font color="gray">MM</font>:::::::::::<font color="gray">MM</font>
                          <font color="gray">MMM</font>::::::::::<font color="gray">MM</font>
                          <font color="gray">MMM</font>::::::::::<font color="gray">MM</font>
                           <font color="gray">MM</font>:::::::::<font color="gray">MM</font>
                           <font color="gray">MMM</font>::::::::<font color="gray">MM</font>
                           <font color="gray">MMM</font>::::::::<font color="gray">MM</font>
                            <font color="gray">MM</font>::::::::<font color="gray">MM</font>
                            <font color="gray">MMM</font>::::::<font color="gray">MM</font>
                            <font color="gray">MMM</font>::::::<font color="gray">MM</font>
                             <font color="gray">MM</font>::::::<font color="gray">MM</font>
                             <font color="gray">MM</font>::::::<font color="gray">MM</font>
                              <font color="gray">MM</font>:::::<font color="gray">MM</font>
                              <font color="gray">MM</font>:::::<font color="gray">MM</font>:
                              <font color="gray">MM</font>:::::<font color="gray">M</font>:<font color="gray">M</font>
                              <font color="gray">MM</font>:::::<font color="gray">M</font>:<font color="gray">M</font>
                              :<font color="gray">M</font>::::::<font color="gray">M</font>:
                             <font color="gray">M</font>:<font color="gray">M</font>:::::::<font color="gray">M</font>
                            <font color="gray">M</font>:::<font color="gray">M</font>::::::<font color="gray">M</font>
                           <font color="gray">M</font>::::<font color="gray">M</font>::::::<font color="gray">M</font>
                          <font color="gray">M</font>:::::<font color="gray">M</font>:::::::<font color="gray">M</font>
                         <font color="gray">M</font>::::::<font color="gray">MM</font>:::::::<font color="gray">M</font>
                         <font color="gray">M</font>:::::::<font color="gray">M</font>::::::::<font color="gray">M</font>
                         <font color="gray">M;</font>:<font color="gray">;</font>::::<font color="gray">M</font>:::::::::<font color="gray">M</font>
                         <font color="gray">M</font>:<font color="gray">m</font>:<font color="gray">;</font>:::<font color="gray">M</font>::::::::::<font color="gray">M</font>
                         <font color="gray">MM</font>:<font color="gray">m</font>:<font color="gray">m</font>::<font color="gray">M</font>::::::::<font color="gray">;</font>:<font color="gray">M</font>
                          <font color="gray">MM</font>:<font color="gray">m</font>::<font color="gray">MM</font>:::::::<font color="gray">;</font>:<font color="gray">;M</font>
                           <font color="gray">MM</font>::<font color="gray">MMM</font>::::::<font color="gray">;</font>:<font color="gray">m</font>:<font color="gray">M</font>
                            <font color="gray">MMMM MM</font>::::<font color="gray">m</font>:<font color="gray">m</font>:<font color="gray">MM</font>
                                  <font color="gray">MM</font>::::<font color="gray">m</font>:<font color="gray">MM</font>
                                   <font color="gray">MM</font>::::<font color="gray">MM</font>
                                    <font color="gray">MM</font>::<font color="gray">MM</font>
                                     <font color="gray">MMMM</font>
</pre></body></html>'''

### REMOTE SERVER CLASSES ###
class HydrusResourceBusyCheck( HydrusServerResources.Resource ):
    def __init__( self ):
        HydrusServerResources.Resource.__init__( self )
        
        self._server_version_string = HC.service_string_lookup[ HC.SERVER_ADMIN ] + '/' + str( HC.NETWORK_VERSION )
        
    
    def render_GET( self, request ):
        request.setResponseCode( 200 )
        request.setHeader( 'Server', self._server_version_string )
        
        if HG.server_busy:
            return b'1'
            
        else:
            return b'0'
            
        
    
class HydrusResourceHydrusNetwork( HydrusServerResources.HydrusResource ):
    def _callbackParseGETArgs( self, request ):
        parsed_request_args = HydrusNetwork.ParseHydrusNetworkGETArgs( request.args )
        request.parsed_request_args = parsed_request_args
        
        return request
        
    
    def _callbackParsePOSTArgs( self, request ):
        request.content.seek( 0 )
        
        if not request.requestHeaders.hasHeader( 'Content-Type' ):
            parsed_request_args = HydrusNetworking.ParsedRequestArguments()
            
        else:
            content_types = request.requestHeaders.getRawHeaders( 'Content-Type' )
            content_type = content_types[0]
            
            try:
                mime = HC.mime_enum_lookup[ content_type ]
                
            except:
                raise HydrusExceptions.BadRequestException( 'Did not recognise Content-Type header!' )
                
            total_bytes_read = 0
            
            if mime == HC.APPLICATION_JSON:
                json_string = request.content.read()
                
                total_bytes_read += len( json_string )
                
                parsed_request_args = HydrusNetwork.ParseNetworkBytesToParsedHydrusArgs( json_string )
                
            else:
                ( os_file_handle, temp_path ) = HydrusPaths.GetTempPath()
                request.temp_file_info = ( os_file_handle, temp_path )
                
                with open( temp_path, 'wb' ) as f:
                    for block in HydrusPaths.ReadFileLikeAsBlocks( request.content ): 
                        f.write( block )
                        
                        total_bytes_read += len( block )
                
                decompression_bombs_ok = self._DecompressionBombsOK( request )
                
                parsed_request_args = HydrusServerResources.ParseFileArguments( temp_path, decompression_bombs_ok )
                
            self._reportDataUsed( request, total_bytes_read )
        
        request.parsed_request_args = parsed_request_args
        
        return request
        

    
class HydrusResourceAccessKey( HydrusResourceHydrusNetwork ):
    def _threadDoGETJob( self, request ):
        registration_key = request.parsed_request_args[ 'registration_key' ]
        access_key = HG.server_controller.Read( 'access_key', self._service_key, registration_key )
        
        body = HydrusNetwork.DumpHydrusArgsToNetworkBytes( { 'access_key' : access_key } )
        response_context = HydrusServerResources.ResponseContext( 200, body = body )
        
        return response_context
        

    
class HydrusResourceShutdown( HydrusResourceHydrusNetwork ):
    def _threadDoPOSTJob( self, request ):
        HG.server_controller.ShutdownFromServer()
        response_context = HydrusServerResources.ResponseContext( 200 )
        
        return response_context
        
    

class HydrusResourceAccessKeyVerification( HydrusResourceHydrusNetwork ):
    def _threadDoGETJob( self, request ):
        access_key = self._parseHydrusNetworkAccessKey( request )
        verified = HG.server_controller.Read( 'verify_access_key', self._service_key, access_key )

        body = HydrusNetwork.DumpHydrusArgsToNetworkBytes( { 'verified' : verified } )
        response_context = HydrusServerResources.ResponseContext( 200, body = body )
        
        return response_context
        
    

class HydrusResourceSessionKey( HydrusResourceHydrusNetwork ):
    def _threadDoGETJob( self, request ):
        access_key = self._parseHydrusNetworkAccessKey( request )
        ( session_key, expires ) = HG.server_controller.server_session_manager.AddSession( self._service_key, access_key )
        
        now = HydrusData.GetNow()
        max_age = expires - now
        cookies = [ ( 'session_key', session_key.hex(), { 'max_age' : str( max_age ), 'path' : '/' } ) ]
        response_context = HydrusServerResources.ResponseContext( 200, cookies = cookies )
        
        return response_context

        
    
class HydrusResourceRestricted( HydrusResourceHydrusNetwork ):
    def _callbackCheckRestrictions( self, request ):
        HydrusResourceHydrusNetwork._callbackCheckRestrictions( self, request )
        
        self._checkSession( request )
        self._checkAccount( request )
        
        return request
        
    
    def _checkAccount( self, request ):
        request.hydrus_account.CheckFunctional()
        
        return request
        
    
    def _checkBandwidth( self, request ):
        if not self._service.BandwidthOK():
            raise HydrusExceptions.BandwidthException( 'This service has run out of bandwidth. Please try again later.' )
            
        if not HG.server_controller.ServerBandwidthOK():
            raise HydrusExceptions.BandwidthException( 'This server has run out of bandwidth. Please try again later.' )
        
    
    def _checkSession( self, request ):
        if not request.requestHeaders.hasHeader( 'Cookie' ):
            raise HydrusExceptions.MissingCredentialsException( 'No cookies found!' )
        
        cookie_texts = request.requestHeaders.getRawHeaders( 'Cookie' )
        cookie_text = cookie_texts[0]
        
        try:
            cookies = http.cookies.SimpleCookie( cookie_text )
            
            if 'session_key' not in cookies:
                session_key = None
                
            else:
                # Morsel, for real, ha ha ha
                morsel = cookies[ 'session_key' ]
                
                session_key_hex = morsel.value
                session_key = bytes.fromhex( session_key_hex )
            
        except:
            raise Exception( 'Problem parsing cookies!' )
        
        account = HG.server_controller.server_session_manager.GetAccount( self._service_key, session_key )
        request.hydrus_account = account
        
        return request
        
    
    def _reportDataUsed( self, request, num_bytes ):
        HydrusResourceHydrusNetwork._reportDataUsed( self, request, num_bytes )
        
        account = request.hydrus_account
        
        if account is not None:
            account.ReportDataUsed( num_bytes )
        
    
    def _reportRequestUsed( self, request ):
        HydrusResourceHydrusNetwork._reportRequestUsed( self, request )
        
        account = request.hydrus_account
        
        if account is not None:
            account.ReportRequestUsed()
            
        
    
class HydrusResourceRestrictedAccount( HydrusResourceRestricted ):
    def _checkAccount( self, request ):
        # you can always fetch your account (e.g. to be notified that you are banned!)
        return request
        
    
    def _threadDoGETJob( self, request ):
        account = request.hydrus_account
        
        body = HydrusNetwork.DumpHydrusArgsToNetworkBytes( { 'account' : account } )
        
        response_context = HydrusServerResources.ResponseContext( 200, body = body )
        
        return response_context
        

    
class HydrusResourceRestrictedAccountInfo( HydrusResourceRestricted ):
    def _threadDoGETJob( self, request ):
        subject_identifier = request.parsed_request_args[ 'subject_identifier' ]
        
        if subject_identifier.HasAccountKey():
            subject_account_key = subject_identifier.GetData()
            
        else:
            raise HydrusExceptions.MissingCredentialsException( 'I was expecting an account key, but did not get one!' )
            
        subject_account = HG.server_controller.Read( 'account', self._service_key, subject_account_key )
        account_info = HG.server_controller.Read( 'account_info', self._service_key, request.hydrus_account, subject_account )
        
        body = HydrusNetwork.DumpHydrusArgsToNetworkBytes( { 'account_info' : account_info } )
        
        response_context = HydrusServerResources.ResponseContext( 200, body = body )
        
        return response_context
        
    
class HydrusResourceRestrictedAccountModification( HydrusResourceRestricted ):
    def _threadDoPOSTJob( self, request ):
        action = request.parsed_request_args[ 'action' ]
        
        subject_accounts = request.parsed_request_args[ 'accounts' ]
        
        kwargs = request.parsed_request_args # for things like expires, title, and so on
        
        with HG.dirty_object_lock:
            HG.server_controller.WriteSynchronous( 'account_modification', self._service_key, request.hydrus_account, action, subject_accounts, **kwargs )
            HG.server_controller.server_session_manager.UpdateAccounts( self._service_key, subject_accounts )
            
        response_context = HydrusServerResources.ResponseContext( 200 )
        
        return response_context

        
    
class HydrusResourceRestrictedAccountTypes( HydrusResourceRestricted ):
    def _threadDoGETJob( self, request ):
        account_types = HG.server_controller.Read( 'account_types', self._service_key, request.hydrus_account )
        
        body = HydrusNetwork.DumpHydrusArgsToNetworkBytes( { 'account_types' : account_types } )
        
        response_context = HydrusServerResources.ResponseContext( 200, body = body )
        
        return response_context
        
    
    def _threadDoPOSTJob( self, request ):
        account_types = request.parsed_request_args[ 'account_types' ]
        deletee_account_type_keys_to_new_account_type_keys = request.parsed_request_args[ 'deletee_account_type_keys_to_new_account_type_keys' ]
        
        HG.server_controller.WriteSynchronous( 'account_types', self._service_key, request.hydrus_account, account_types, deletee_account_type_keys_to_new_account_type_keys )
        HG.server_controller.server_session_manager.RefreshAccounts( self._service_key )
        
        response_context = HydrusServerResources.ResponseContext( 200 )
        
        return response_context
        

    
class HydrusResourceRestrictedBackup( HydrusResourceRestricted ):
    def _threadDoPOSTJob( self, request ):
        # check permission here since this is an asynchronous job
        request.hydrus_account.CheckPermission( HC.CONTENT_TYPE_SERVICES, HC.PERMISSION_ACTION_OVERRULE )
        
        HG.server_controller.Write( 'backup' )
        
        response_context = HydrusServerResources.ResponseContext( 200 )
        
        return response_context
        
    

class HydrusResourceRestrictedIP( HydrusResourceRestricted ):
    def _threadDoGETJob( self, request ):
        hash = request.parsed_request_args[ 'hash' ]
        ( ip, timestamp ) = HG.server_controller.Read( 'ip', self._service_key, request.hydrus_account, hash )
        
        body = HydrusNetwork.DumpHydrusArgsToNetworkBytes( { 'ip' : ip, 'timestamp' : timestamp } )
        
        response_context = HydrusServerResources.ResponseContext( 200, body = body )
        
        return response_context
        
    

class HydrusResourceRestrictedNumPetitions( HydrusResourceRestricted ):
    def _threadDoGETJob( self, request ):
        petition_count_info = HG.server_controller.Read( 'num_petitions', self._service_key, request.hydrus_account )
        body = HydrusNetwork.DumpHydrusArgsToNetworkBytes( { 'num_petitions' : petition_count_info } )
        
        response_context = HydrusServerResources.ResponseContext( 200, body = body )
        
        return response_context
        

    
class HydrusResourceRestrictedPetition( HydrusResourceRestricted ):
    def _threadDoGETJob( self, request ):
        content_type = request.parsed_request_args[ 'content_type' ]
        status = request.parsed_request_args[ 'status' ]
        
        petition = HG.server_controller.Read( 'petition', self._service_key, request.hydrus_account, content_type, status )
        
        body = HydrusNetwork.DumpHydrusArgsToNetworkBytes( { 'petition' : petition } )
        
        response_context = HydrusServerResources.ResponseContext( 200, body = body )
        
        return response_context
        
    

class HydrusResourceRestrictedRegistrationKeys( HydrusResourceRestricted ):
    def _threadDoGETJob( self, request ):
        num = request.parsed_request_args[ 'num' ]
        account_type_key = request.parsed_request_args[ 'account_type_key' ]
        
        if 'expires' in request.parsed_request_args:
            expires = request.parsed_request_args[ 'expires' ]
            
        else:
            expires = None
        
        registration_keys = HG.server_controller.Read( 'registration_keys', self._service_key, request.hydrus_account, num, account_type_key, expires )
        
        body = HydrusNetwork.DumpHydrusArgsToNetworkBytes( { 'registration_keys' : registration_keys } )
        
        response_context = HydrusServerResources.ResponseContext( 200, body = body )
        
        return response_context
        

    
class HydrusResourceRestrictedRepositoryFile( HydrusResourceRestricted ):
    def _DecompressionBombsOK( self, request ):
        return request.hydrus_account.HasPermission( HC.CONTENT_TYPE_ACCOUNTS, HC.PERMISSION_ACTION_CREATE )
        
    
    def _threadDoGETJob( self, request ):
        self._checkBandwidth( request )
        
        # no permission check as any functional account can get files
        hash = request.parsed_request_args[ 'hash' ]
        
        ( valid, mime ) = HG.server_controller.Read( 'service_has_file', self._service_key, hash )
        
        if not valid:
            raise HydrusExceptions.NotFoundException( 'File not found on this service!' )
        
        path = ServerFiles.GetFilePath( hash )
        
        response_context = HydrusServerResources.ResponseContext( 200, mime = mime, path = path )
        
        return response_context
        
    
    def _threadDoPOSTJob( self, request ):
        file_dict = request.parsed_request_args
        
        if self._service.LogUploaderIPs():
            file_dict[ 'ip' ] = request.getClientIP()
            
        HG.server_controller.WriteSynchronous( 'file', self._service, request.hydrus_account, file_dict )
        
        response_context = HydrusServerResources.ResponseContext( 200 )
        
        return response_context
        
    

class HydrusResourceRestrictedRepositoryThumbnail( HydrusResourceRestricted ):
    def _threadDoGETJob( self, request ):
        self._checkBandwidth( request )
        # no permission check as any functional account can get thumbnails
        
        hash = request.parsed_request_args[ 'hash' ]
        ( valid, mime ) = HG.server_controller.Read( 'service_has_file', self._service_key, hash )
        
        if not valid:
            raise HydrusExceptions.NotFoundException( 'Thumbnail not found on this service!' )
        
        if mime not in HC.MIMES_WITH_THUMBNAILS:
            raise HydrusExceptions.NotFoundException( 'That mime should not have a thumbnail!' )
            
        path = ServerFiles.GetThumbnailPath( hash )
        
        response_context = HydrusServerResources.ResponseContext( 200, mime = HC.APPLICATION_OCTET_STREAM, path = path )
        
        return response_context

        
    
class HydrusResourceRestrictedServices( HydrusResourceRestricted ):
    def _threadDoGETJob( self, request ):
        services = HG.server_controller.Read( 'services_from_account', request.hydrus_account )
        
        body = HydrusNetwork.DumpHydrusArgsToNetworkBytes( { 'services' : services } )
        
        response_context = HydrusServerResources.ResponseContext( 200, body = body )
        
        return response_context
        
    
    def _threadDoPOSTJob( self, request ):
        services = request.parsed_request_args[ 'services' ]
        unique_ports = { service.GetPort() for service in services }
        
        if len( unique_ports ) < len( services ):
            raise HydrusExceptions.BadRequestException( 'It looks like some of those services share ports! Please give them unique ports!' )
        
        with HG.dirty_object_lock:
            service_keys_to_access_keys = HG.server_controller.WriteSynchronous( 'services', request.hydrus_account, services )
            
            HG.server_controller.SetServices( services )
        
        body = HydrusNetwork.DumpHydrusArgsToNetworkBytes( { 'service_keys_to_access_keys' : service_keys_to_access_keys } )
        
        response_context = HydrusServerResources.ResponseContext( 200, body = body )
        
        return response_context
        

    
class HydrusResourceRestrictedUpdate( HydrusResourceRestricted ):
    def _threadDoGETJob( self, request ):
        self._checkBandwidth( request )
        # no permissions check as any functional account can get updates
        
        update_hash = request.parsed_request_args[ 'update_hash' ]
        
        if not self._service.HasUpdateHash( update_hash ):
            raise HydrusExceptions.NotFoundException( 'This update hash does not exist on this service!' )
            
        path = ServerFiles.GetFilePath( update_hash )
        
        response_context = HydrusServerResources.ResponseContext( 200, mime = HC.APPLICATION_OCTET_STREAM, path = path )
        
        return response_context
        
    
    def _threadDoPOSTJob( self, request ):
        client_to_server_update = request.parsed_request_args[ 'client_to_server_update' ]
        HG.server_controller.WriteSynchronous( 'update', self._service_key, request.hydrus_account, client_to_server_update )
        
        response_context = HydrusServerResources.ResponseContext( 200 )
        
        return response_context
        

    
class HydrusResourceRestrictedImmediateUpdate( HydrusResourceRestricted ):
    def _threadDoGETJob( self, request ):
        updates = HG.server_controller.Read( 'immediate_update', self._service_key, request.hydrus_account )
        updates = HydrusSerialisable.SerialisableList( updates )
        
        body = HydrusNetwork.DumpHydrusArgsToNetworkBytes( { 'updates' : updates } )
        
        response_context = HydrusServerResources.ResponseContext( 200, body = body )
        
        return response_context
        
        
    
class HydrusResourceRestrictedMetadataUpdate( HydrusResourceRestricted ):
    def _threadDoGETJob( self, request ):
        # no permissions check as any functional account can get metadata slices
        
        since = request.parsed_request_args[ 'since' ]
        
        metadata_slice = self._service.GetMetadataSlice( since )
        
        body = HydrusNetwork.DumpHydrusArgsToNetworkBytes( { 'metadata_slice' : metadata_slice } )
        
        response_context = HydrusServerResources.ResponseContext( 200, body = body )
        
        return response_context
        
    
