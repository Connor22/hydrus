### IMPORTS ###
from . import HydrusConstants as HC
from . import HydrusExceptions
from . import HydrusGlobals as HG
from . import HydrusSerialisable
from . import HydrusText
from . import HydrusPaths
from . import HydrusTags

from . import ClientConstants as CC
from . import ClientDefaults
from . import ClientDownloading
from . import ClientThreading

import bs4
import collections
import cProfile
import io
import locale
import os
import pstats
import psutil
import random
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import traceback
import yaml
import itertools
import wx
import wx.lib.colourutils


### CODE ###
def AddPaddingToDimensions( dimensions, padding ):
    
    ( x, y ) = dimensions
    
    return ( x + padding, y + padding )

def default_dict_list(): return collections.defaultdict( list )

def default_dict_set(): return collections.defaultdict( set )

def BuildKeyToListDict( pairs ):
    
    d = collections.defaultdict( list )
    
    for ( key, value ) in pairs: d[ key ].append( value )
    
    return d
    
def BuildKeyToSetDict( pairs ):
    
    d = collections.defaultdict( set )
    
    for ( key, value ) in pairs: d[ key ].add( value )
    
    return d
    
def CalculateScoreFromRating( count, rating ):
    
    # http://www.evanmiller.org/how-not-to-sort-by-average-rating.html
    
    positive = count * rating
    negative = count * ( 1.0 - rating )
    
    # positive + negative = count
    
    # I think I've parsed this correctly from the website! Not sure though!
    score = ( ( positive + 1.9208 ) / count - 1.96 * ( ( ( positive * negative ) / count + 0.9604 ) ** 0.5 ) / count ) / ( 1 + 3.8416 / count )
    
    return score
    
def CleanRunningFile( db_path, instance ):
    
    path = os.path.join( db_path, instance + '_running' )
    
    try:
        
        os.remove( path )
        
    except:
        
        pass
        
def ConvertFloatToPercentage( f ):
    
    return '{:.1f}%'.format( f * 100 )
    
def ConvertIntToFirst( n ):
    
    # straight from stack, wew
    return "%d%s" % (n,"tsnrhtdd"[(n/10%10!=1)*(n%10<4)*n%10::4])
    
def ConvertIntToPixels( i ):
    
    if i == 1: return 'pixels'
    elif i == 1000: return 'kilopixels'
    elif i == 1000000: return 'megapixels'
    else: return 'megapixels'
    
def ConvertIntToPrettyOrdinalString( num ):
    
    remainder = num % 10
    
    if remainder == 1:
        
        ordinal = 'st'
        
    elif remainder == 2:
        
        ordinal = 'nd'
        
    elif remainder == 3:
        
        ordinal = 'rd'
        
    else:
        
        ordinal = 'th'
        
    
    return ToHumanInt( num ) + ordinal
    
def ConvertIntToUnit( unit ):
    
    if unit == 1: return 'B'
    elif unit == 1024: return 'KB'
    elif unit == 1048576: return 'MB'
    elif unit == 1073741824: return 'GB'
    
def ConvertMillisecondsToPrettyTime( ms ):
    
    hours = ms // 3600000
    
    if hours == 1: hours_result = '1 hour'
    else: hours_result = str( hours ) + ' hours'
    
    ms = ms % 3600000
    
    minutes = ms // 60000
    
    if minutes == 1: minutes_result = '1 minute'
    else: minutes_result = str( minutes ) + ' minutes'
    
    ms = ms % 60000
    
    seconds = ms // 1000
    
    if seconds == 1: seconds_result = '1 second'
    else: seconds_result = str( seconds ) + ' seconds'
    
    detailed_seconds = ms / 1000
    
    detailed_seconds_result = '{:.1f} seconds'.format( detailed_seconds )
    
    ms = ms % 1000
    
    if hours > 0: return hours_result + ' ' + minutes_result
    
    if minutes > 0: return minutes_result + ' ' + seconds_result
    
    if seconds > 0: return detailed_seconds_result
    
    ms = int( ms )
    
    if ms == 1: milliseconds_result = '1 millisecond'
    else: milliseconds_result = '{} milliseconds'.format( ms )
    
    return milliseconds_result
    
def ConvertNumericalRatingToPrettyString( lower, upper, rating, rounded_result = False, out_of = True ):
    
    rating_converted = ( rating * ( upper - lower ) ) + lower
    
    if rounded_result:
        
        rating_converted = round( rating_converted )
        
    
    s = '{:.2f}'.format( rating_converted )
    
    if out_of and lower in ( 0, 1 ):
        
        s += '/{:.2f}'.format( upper )
        
    
    return s
    
def ConvertPixelsToInt( unit ):
    
    if unit == 'pixels': return 1
    elif unit == 'kilopixels': return 1000
    elif unit == 'megapixels': return 1000000
    
def ConvertPrettyStringsToUglyNamespaces( pretty_strings ):
    
    result = { s for s in pretty_strings if s != 'no namespace' }
    
    if 'no namespace' in pretty_strings: result.add( '' )
    
    return result
    
def ConvertResolutionToPrettyString( resolution ):
    
    ( width, height ) = resolution
    
    return ToHumanInt( width ) + 'x' + ToHumanInt( height )
    
def ConvertStatusToPrefix( status ):
    
    if status == HC.CONTENT_STATUS_CURRENT: return ''
    elif status == HC.CONTENT_STATUS_PENDING: return '(+) '
    elif status == HC.CONTENT_STATUS_PETITIONED: return '(-) '
    elif status == HC.CONTENT_STATUS_DELETED: return '(X) '
    
def TimeDeltaToPrettyTimeDelta( seconds ):
    
    if seconds is None:
        
        return 'per month'
        
    
    if seconds == 0:
        
        return '0 seconds'
        
    
    if seconds < 0:
        
        seconds = abs( seconds )
        
    
    if seconds >= 60:
        
        seconds = int( seconds )
        
        MINUTE = 60
        HOUR = 60 * MINUTE
        DAY = 24 * HOUR
        MONTH = 30 * DAY
        YEAR = 12 * MONTH
        
        lines = []
        
        lines.append( ( 'year', YEAR ) )
        lines.append( ( 'month', MONTH ) )
        lines.append( ( 'day', DAY ) )
        lines.append( ( 'hour', HOUR ) )
        lines.append( ( 'minute', MINUTE ) )
        lines.append( ( 'second', 1 ) )
        
        result_components = []
        
        for ( time_string, duration ) in lines:
            
            time_quantity = seconds // duration
            
            seconds %= duration
            
            if time_quantity > 0:
                
                s = ToHumanInt( time_quantity ) + ' ' + time_string
                
                if time_quantity > 1:
                    
                    s += 's'
                    
                
                result_components.append( s )
                
                if len( result_components ) == 2: # we now have 1 month 2 days
                    
                    break
                    
                
            else:
                
                if len( result_components ) > 0: # something like '1 year' -- in which case we do not care about the days and hours
                    
                    break
                    
                
            
        
        result = ' '.join( result_components )
        
    elif seconds > 1:
        
        if int( seconds ) == seconds:
            
            result = ToHumanInt( seconds ) + ' seconds'
            
        else:
            
            result = '{:.1f} seconds'.format( seconds )
            
        
    elif seconds == 1:
        
        result = '1 second'
        
    elif seconds > 0.1:
        
        result = '{} milliseconds'.format( int( seconds * 1000 ) )
        
    elif seconds > 0.01:
        
        result = '{:.1f} milliseconds'.format( int( seconds * 1000 ) )
        
    elif seconds > 0.001:
        
        result = '{:.2f} milliseconds'.format( int( seconds * 1000 ) )
        
    else:
        
        result = '{} microseconds'.format( int( seconds * 1000000 ) )
        
    
    return result
    
def ConvertTimestampToPrettyExpires( timestamp ):
    
    if timestamp is None:
        
        return 'does not expire'
        
    
    if timestamp == 0:
        
        return 'unknown expiration'
        
    
    time_delta_string = TimestampToPrettyTimeDelta( timestamp )
    
    if TimeHasPassed( timestamp ):
        
        return 'expired ' + time_delta_string
        
    else:
        return 'expires ' + time_delta_string
        
def ConvertTimestampToPrettyTime( timestamp, in_gmt = False, include_24h_time = True ):
    
    if include_24h_time:
        
        phrase = '%Y/%m/%d %H:%M:%S'
        
    else:
        
        phrase = '%Y/%m/%d'
        
    
    if in_gmt:
        
        struct_time = time.gmtime( timestamp )
        
        phrase = phrase + ' GMT'
        
    else:
        
        struct_time = time.localtime( timestamp )
        
    
    return time.strftime( phrase, struct_time )
    
def TimestampToPrettyTimeDelta( timestamp, just_now_string = 'now', just_now_threshold = 3 ):
    
    if timestamp is None:
        
        timestamp = 0
        
    
    if HG.client_controller.new_options.GetBoolean( 'always_show_iso_time' ):
        
        return ConvertTimestampToPrettyTime( timestamp )
        
    
    time_delta = abs( timestamp - GetNow() )
    
    if time_delta <= just_now_threshold:
        
        return just_now_string
        
    
    time_delta_string = TimeDeltaToPrettyTimeDelta( time_delta )
    
    if TimeHasPassed( timestamp ):
        
        return time_delta_string + ' ago'
        
    else:
        
        return 'in ' + time_delta_string
    
def ConvertUglyNamespaceToPrettyString( namespace ):
    
    if namespace is None or namespace == '':
        
        return 'no namespace'
        
    else:
        
        return namespace
    
def ConvertUglyNamespacesToPrettyStrings( namespaces ):
    
    namespaces = list( namespaces )
    
    namespaces.sort()
    
    result = [ ConvertUglyNamespaceToPrettyString( namespace ) for namespace in namespaces ]
    
    return result
    
def ConvertUnitToInt( unit ):
    
    if unit == 'B': return 1
    elif unit == 'KB': return 1024
    elif unit == 'MB': return 1048576
    elif unit == 'GB': return 1073741824
    
def ConvertValueRangeToBytes( value, range ):
    
    return ToHumanBytes( value ) + '/' + ToHumanBytes( range )
    
def ConvertValueRangeToPrettyString( value, range ):
    
    return ToHumanInt( value ) + '/' + ToHumanInt( range )
    
def ConvertValueRangeToScanbarTimestampsMS( value_ms, range_ms ):
    
    value_ms = int( round( value_ms ) )
    
    range_hours = range_ms // 3600000
    value_hours = value_ms // 3600000
    range_minutes = ( range_ms % 3600000 ) // 60000
    value_minutes = ( value_ms % 3600000 ) // 60000
    range_seconds = ( range_ms % 60000 ) // 1000
    value_seconds = ( value_ms % 60000 ) // 1000
    range_ms = range_ms % 1000
    value_ms = value_ms % 1000
    
    if range_hours > 0:
        
        # 0:01:23.033/1:12:57.067
        
        time_phrase = '{}:{:0>2}:{:0>2}.{:0>3}'
        
        args = ( value_hours, value_minutes, value_seconds, value_ms, range_hours, range_minutes, range_seconds, range_ms )
        
    elif range_minutes > 0:
        
        # 01:23.033/12:57.067 or 0:23.033/1:57.067
        
        if range_minutes > 9:
            
            time_phrase = '{:0>2}:{:0>2}.{:0>3}'
            
        else:
            
            time_phrase = '{:0>1}:{:0>2}.{:0>3}'
            
        
        args = ( value_minutes, value_seconds, value_ms, range_minutes, range_seconds, range_ms )
        
    else:
        
        # 23.033/57.067 or 3.033/7.067 or 0.033/0.067
        
        if range_seconds > 9:
            
            time_phrase = '{:0>2}.{:0>3}'
            
        else:
            
            time_phrase = '{:0>1}.{:0>3}'
            
        
        args = ( value_seconds, value_ms, range_seconds, range_ms )
        
    
    full_phrase = '{}/{}'.format( time_phrase, time_phrase )
    
    result = full_phrase.format( *args )
    
    return result
    
def DebugPrint( debug_info ):
    
    Print( debug_info )
    
    sys.stdout.flush()
    sys.stderr.flush()
    
def DedupeList( xs ):
    
    xs_seen = set()
    
    xs_return = []
    
    for x in xs:
        
        if x in xs_seen:
            
            continue
            
        
        xs_return.append( x )
        
        xs_seen.add( x )
        
    
    return xs_return
    
def GenerateKey():
    
    return os.urandom( HC.HYDRUS_KEY_LENGTH )
    
def Get64BitHammingDistance( phash1, phash2 ):
    
    # old way of doing this was:
    #while xor > 0:
    #    
    #    distance += 1
    #    xor &= xor - 1
    #    
    
    # convert to unsigned long long, then xor
    # then through the power of stackexchange magic, we get number of bits in record time
    # Here it is: https://stackoverflow.com/questions/9829578/fast-way-of-counting-non-zero-bits-in-positive-integer/9830282#9830282
    
    n = struct.unpack( '!Q', phash1 )[0] ^ struct.unpack( '!Q', phash2 )[0]
    
    n = ( n & 0x5555555555555555 ) + ( ( n & 0xAAAAAAAAAAAAAAAA ) >> 1 ) # 10101010, 01010101
    n = ( n & 0x3333333333333333 ) + ( ( n & 0xCCCCCCCCCCCCCCCC ) >> 2 ) # 11001100, 00110011
    n = ( n & 0x0F0F0F0F0F0F0F0F ) + ( ( n & 0xF0F0F0F0F0F0F0F0 ) >> 4 ) # 11110000, 00001111
    n = ( n & 0x00FF00FF00FF00FF ) + ( ( n & 0xFF00FF00FF00FF00 ) >> 8 ) # etc...
    n = ( n & 0x0000FFFF0000FFFF ) + ( ( n & 0xFFFF0000FFFF0000 ) >> 16 )
    n = ( n & 0x00000000FFFFFFFF ) + ( n >> 32 )
    
    # you technically are going n & 0xFFFFFFFF00000000 at the end, but that's a no-op with the >> 32 afterwards, so can be omitted
    
    return n
    
def GetEmptyDataDict():
    
    data = collections.defaultdict( default_dict_list )
    
    return data
    
def GetNow():
    
    return int( time.time() )
    
def GetNowFloat():
    
    return time.time()
    
def GetNowPrecise():
    
    if HC.PLATFORM_WINDOWS:
        
        return time.clock()
        
    else:
        
        return time.time()
    
def GetSiblingProcessPorts( db_path, instance ):
    
    path = os.path.join( db_path, instance + '_running' )
    
    if os.path.exists( path ):
        
        with open( path, 'r', encoding = 'utf-8' ) as f:
            
            file_text = f.read()
            
            try:
                
                ( pid, create_time ) = HydrusText.DeserialiseNewlinedTexts( file_text )
                
                pid = int( pid )
                create_time = float( create_time )
                
            except ValueError:
                
                return None
                
            
            try:
                
                if psutil.pid_exists( pid ):
                    
                    ports = []
                    
                    p = psutil.Process( pid )
                    
                    for conn in p.connections():
                        
                        if conn.status == 'LISTEN':
                            
                            ports.append( int( conn.laddr[1] ) )
                            
                        
                    
                    return ports
                    
                
            except psutil.Error:
                
                return None
                
            
        
    
    return None
    
def GetSubprocessEnv():
    
    if HC.RUNNING_FROM_FROZEN_BUILD:
        
        if HG.subprocess_report_mode:
            
            env = os.environ.copy()
            
            ShowText( 'Your pyinstaller env is: {}'.format( env ) )
            
        
        # let's make a proper env for subprocess that doesn't have pyinstaller woo woo in it
        
        env = os.environ.copy()
        
        changes_made = False
        
        lp_key = 'LD_LIBRARY_PATH'
        lp_orig_key = lp_key + '_ORIG'
        
        if lp_orig_key in env:
            
            env[ lp_key ] = env[ lp_orig_key ]
            
            changes_made = True
            
        
        if ( HC.PLATFORM_LINUX or HC.PLATFORM_OSX ) and 'PATH' in env:
            
            # fix for pyinstaller, which drops this stuff for some reason and hence breaks ffmpeg
            
            path = env[ 'PATH' ]
            
            path_locations = set( path.split( ':' ) )
            desired_path_locations = [ '/usr/bin', '/usr/local/bin' ]
            
            for desired_path_location in desired_path_locations:
                
                if desired_path_location not in path_locations:
                    
                    path = desired_path_location + ':' + path
                    
                    env[ 'PATH' ] = path
                    
                    changes_made = True
                    
                
            
        
        if not changes_made:
            
            env = None
            
        
    else:
        
        env = None
        
    
    return env
    
def GetSubprocessHideTerminalStartupInfo():
    
    if HC.PLATFORM_WINDOWS:
        
        # This suppresses the terminal window that tends to pop up when calling ffmpeg or whatever
        
        startupinfo = subprocess.STARTUPINFO()
        
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
    else:
        
        startupinfo = None
        
    
    return startupinfo
    
def GetSubprocessKWArgs( hide_terminal = True, text = False ):
    
    sbp_kwargs = {}
    
    sbp_kwargs[ 'env' ] = GetSubprocessEnv()
    
    if text:
        
        # probably need to override the stdXXX pipes with i/o encoding wrappers in the case of 3.5 here
        
        if sys.version_info.minor >= 6:
            
            sbp_kwargs[ 'encoding' ] = 'utf-8'
            
        
        if sys.version_info.minor >= 7:
            
            sbp_kwargs[ 'text' ] = True
            
        else:
            
            sbp_kwargs[ 'universal_newlines' ] = True
            
        
    
    if hide_terminal:
        
        sbp_kwargs[ 'startupinfo' ] = GetSubprocessHideTerminalStartupInfo()
        
    
    if HG.subprocess_report_mode:
        
        message = 'KWargs are: {}'.format( sbp_kwargs )
        
    
    return sbp_kwargs
    
def GetTimeDeltaSinceTime( timestamp ):
    
    time_since = timestamp - GetNow()
    
    result = min( time_since, 0 )
    
    return - result
    
def GetTimeDeltaUntilTime( timestamp ):
    
    time_remaining = timestamp - GetNow()
    
    return max( time_remaining, 0 )
    
def GetTimeDeltaUntilTimeFloat( timestamp ):
    
    time_remaining = timestamp - GetNowFloat()
    
    return max( time_remaining, 0.0 )
    
def GetTimeDeltaUntilTimePrecise( t ):
    
    time_remaining = t - GetNowPrecise()
    
    return max( time_remaining, 0.0 )
    
def GetTypeName( obj_type ):
    
    if hasattr( obj_type, '__name__' ):
        
        return obj_type.__name__
        
    else:
        
        return repr( obj_type )
    
def GenerateHumanTextSortKey():
    """Solves the 19, 20, 200, 21, 22 issue when sorting 'Page 21.jpg' type strings.
    Breaks the string into groups of text and int (i.e. ( "Page ", 21, ".jpg" ) )."""
    
    int_convert = lambda t: int( t ) if t.isdecimal() else t
    
    split_alphanum = lambda t: tuple( ( int_convert( sub_t ) for sub_t in re.split( '([0-9]+)', t.lower() ) ) )
    
    return split_alphanum
    
HumanTextSortKey = GenerateHumanTextSortKey()

def HumanTextSort( texts ):
    
    texts.sort( key = HumanTextSortKey ) 
    
def IntelligentMassIntersect( sets_to_reduce ):
    
    answer = None
    
    def get_len( item ):
        
        return len( item )
        
    
    for set_to_reduce in sets_to_reduce:
        
        if len( set_to_reduce ) == 0:
            
            return set()
            
        
        if answer is None:
            
            answer = set( set_to_reduce )
            
        else:
            
            if len( answer ) == 0:
                
                return set()
                
            else:
                
                answer.intersection_update( set_to_reduce )
                
            
        
    
    if answer is None:
        
        return set()
        
    else:
        
        return answer
    
def IsAlreadyRunning( db_path, instance ):
    
    path = os.path.join( db_path, instance + '_running' )
    
    if os.path.exists( path ):
        
        with open( path, 'r', encoding = 'utf-8' ) as f:
            
            file_text = f.read()
            
            try:
                
                ( pid, create_time ) = HydrusText.DeserialiseNewlinedTexts( file_text )
                
                pid = int( pid )
                create_time = float( create_time )
                
            except ValueError:
                
                return False
                
            
            try:
                
                me = psutil.Process()
                
                if me.pid == pid and me.create_time() == create_time:
                    
                    # this is me! there is no conflict, lol!
                    # this happens when a linux process restarts with os.execl(), for instance (unlike Windows, it keeps its pid)
                    
                    return False
                    
                
                if psutil.pid_exists( pid ):
                    
                    p = psutil.Process( pid )
                    
                    if p.create_time() == create_time and p.is_running():
                        
                        return True
                        
                    
                
            except psutil.Error:
                
                return False
                
            
        
    
    return False
    
def IterateHexPrefixes():
    
    hex_chars = '0123456789abcdef'
    
    for ( one, two ) in itertools.product( hex_chars, hex_chars ):
        
        prefix = one + two
        
        yield prefix
    
def LastShutdownWasBad( db_path, instance ):
    
    path = os.path.join( db_path, instance + '_running' )
    
    if os.path.exists( path ):
        
        return True
        
    else:
        
        return False

def MassUnion( lists ):
    
    return { item for item in itertools.chain.from_iterable( lists ) }
    
def MedianPop( population ):
    
    # assume it has at least one and comes sorted
    
    median_index = len( population ) // 2
    
    row = population.pop( median_index )
    
    return row
    
def MergeKeyToListDicts( key_to_list_dicts ):
    
    result = collections.defaultdict( list )
    
    for key_to_list_dict in key_to_list_dicts:
        
        for ( key, value ) in list(key_to_list_dict.items()): result[ key ].extend( value )
        
    
    return result
    
def Print( text ):
    
    try:
        
        print( str( text ) )
        
    except:
        
        print( repr( text ) )
    
ShowText = Print

def PrintException( e, do_wait = True ):
    
    if isinstance( e, HydrusExceptions.ShutdownException ):
        
        return
        
    
    etype = type( e )
    
    ( etype, value, tb ) = sys.exc_info()
    
    if etype is None:
        
        etype = type( e )
        value = str( e )
        
        trace = 'No error trace'
        
    else:
        
        trace = ''.join( traceback.format_exception( etype, value, tb ) )
        
    
    stack_list = traceback.format_stack()
    
    stack = ''.join( stack_list )
    
    message = str( etype.__name__ ) + ': ' + str( value ) + os.linesep + trace + os.linesep + stack
    
    Print( '' )
    Print( 'Exception:' )
    
    DebugPrint( message )
    
    if do_wait:
        
        time.sleep( 1 )
    
ShowException = PrintException

def Profile( summary, code, g, l, min_duration_ms = 20 ):
    
    profile = cProfile.Profile()
    
    started = GetNowPrecise()
    
    profile.runctx( code, g, l )
    
    finished = GetNowPrecise()
    
    time_took = finished - started
    time_took_ms = int( time_took * 1000.0 )
    
    if time_took_ms > min_duration_ms:
        
        output = io.StringIO()
        
        stats = pstats.Stats( profile, stream = output )
        
        stats.strip_dirs()
        
        stats.sort_stats( 'tottime' )
        
        output.write( 'Stats' )
        output.write( os.linesep * 2 )
        
        stats.print_stats()
        
        output.write( 'Callers' )
        output.write( os.linesep * 2 )
        
        stats.print_callers()
        
        output.seek( 0 )
        
        details = output.read()
        
    else:
        
        summary += ' - It took ' + TimeDeltaToPrettyTimeDelta( time_took ) + '.'
        
        details = ''
        
    
    HG.controller.PrintProfile( summary, details )
    
def RandomPop( population ):
    
    random_index = random.randint( 0, len( population ) - 1 )
    
    row = population.pop( random_index )
    
    return row
    
def RecordRunningStart( db_path, instance ):
    
    path = os.path.join( db_path, instance + '_running' )
    
    record_string = ''
    
    try:
        
        me = psutil.Process()
        
        record_string += str( me.pid )
        record_string += os.linesep
        record_string += str( me.create_time() )
        
    except psutil.Error:
        
        return
        
    
    with open( path, 'w', encoding = 'utf-8' ) as f:
        
        f.write( record_string )
    
def RestartProcess():
    
    time.sleep( 1 ) # time for ports to unmap
    
    exe = sys.executable
    me = sys.argv[0]
    
    if HC.RUNNING_FROM_SOURCE:
        
        # exe is python's exe, me is the script
        
        args = [ sys.executable ] + sys.argv
        
    else:
        
        # we are running a frozen release--both exe and me are the built exe
        # wrap it in quotes because pyinstaller passes it on as raw text, breaking any path with spaces :/
        
        args = [ '"' + me + '"' ] + sys.argv[1:]
        
    
    os.execv( exe, args )
    
def SplayListForDB( xs ):
    
    return '(' + ','.join( ( str( x ) for x in xs ) ) + ')'
    
def SplitIteratorIntoChunks( iterator, n ):
    
    chunk = []
    
    for item in iterator:
        
        chunk.append( item )
        
        if len( chunk ) == n:
            
            yield chunk
            
            chunk = []
            
        
    
    if len( chunk ) > 0:
        
        yield chunk

def SplitListIntoChunks( xs, n ):
    
    if isinstance( xs, set ):
        
        xs = list( xs )
        
    
    for i in range( 0, len( xs ), n ):
        
        yield xs[ i : i + n ]
        
def SplitMappingListIntoChunks( xs, n ):
    
    chunk_weight = 0
    chunk = []
    
    for ( tag_item, hash_items ) in xs:
        
        for chunk_of_hash_items in SplitListIntoChunks( hash_items, n ):
            
            chunk.append( ( tag_item, chunk_of_hash_items ) )
            
            chunk_weight += len( chunk_of_hash_items )
            
            if chunk_weight > n:
                
                yield chunk
                
                chunk_weight = 0
                chunk = []
                
            
        
    
    if len( chunk ) > 0:
        
        yield chunk
        
def TimeHasPassed( timestamp ):
    
    if timestamp is None:
        
        return False
        
    
    return GetNow() > timestamp
    
def TimeHasPassedFloat( timestamp ):
    
    return GetNowFloat() > timestamp
    
def TimeHasPassedPrecise( precise_timestamp ):
    
    return GetNowPrecise() > precise_timestamp
    
def TimeUntil( timestamp ):
    
    return timestamp - GetNow()
    
def ToHumanBytes( size ):
    
    if size is None:
        
        return 'unknown size'
        
    
    if size < 1024:
        
        return ToHumanInt( size ) + 'B'
        
    
    suffixes = ( '', 'K', 'M', 'G', 'T', 'P' )
    
    suffix_index = 0
    
    while size >= 1024:
        
        size = size / 1024
        
        suffix_index += 1
        
    
    suffix = suffixes[ suffix_index ]
    
    if size < 10.0:
        
        # 3.1MB
        
        return '{:.1f}{}B'.format( size, suffix )
        
    else:
        
        # 23MB
        
        return '{:.0f}{}B'.format( size, suffix )
    
def ToHumanInt( num ):
    
    text = locale.format_string( '%d', num, grouping = True )
    
    return text
    
def WaitForProcessToFinish( p, timeout ):
    
    started = GetNow()
    
    while p.poll() is None:
        
        if TimeHasPassed( started + timeout ):
            
            p.kill()
            
            raise Exception( 'Process did not finish within ' + ToHumanInt( timeout ) + ' seconds!' )
            
        
        time.sleep( 2 )

def CatchExceptionClient( etype, value, tb ):
    
    try:
        
        trace_list = traceback.format_tb( tb )
        
        trace = ''.join( trace_list )
        
        pretty_value = str( value )
        
        if os.linesep in pretty_value:
            
            ( first_line, anything_else ) = pretty_value.split( os.linesep, 1 )
            
            trace = trace + os.linesep + anything_else
            
        else:
            
            first_line = pretty_value
            
        
        job_key = ClientThreading.JobKey()
        
        if etype == HydrusExceptions.ShutdownException:
            
            return
            
        else:
            
            try: job_key.SetVariable( 'popup_title', str( etype.__name__ ) )
            except: job_key.SetVariable( 'popup_title', str( etype ) )
            
            job_key.SetVariable( 'popup_text_1', first_line )
            job_key.SetVariable( 'popup_traceback', trace )
            
        
        text = job_key.ToString()
        
        HydrusData.Print( 'Uncaught exception:' )
        
        HydrusData.DebugPrint( text )
        
        HG.client_controller.pub( 'message', job_key )
        
    except:
        
        text = 'Encountered an error I could not parse:'
        
        text += os.linesep
        
        text += str( ( etype, value, tb ) )
        
        try: text += traceback.format_exc()
        except: pass
        
        HydrusData.ShowText( text )
        
    
    time.sleep( 1 )
    
def ColourIsBright( colour ):
    
    ( r, g, b, a ) = colour.Get()
    
    brightness_estimate = ( r + g + b ) // 3
    
    it_is_bright = brightness_estimate > 127
    
    return it_is_bright
    
def ColourIsGreyish( colour ):
    
    ( r, g, b, a ) = colour.Get()
    
    greyish = r // 16 == g // 16 and g // 16 == b // 16
    
    return greyish
    
def ConvertServiceKeysToContentUpdatesToPrettyString( service_keys_to_content_updates ):
    
    num_files = 0
    actions = set()
    locations = set()
    
    extra_words = ''
    
    for ( service_key, content_updates ) in list(service_keys_to_content_updates.items()):
        
        if len( content_updates ) > 0:
            
            name = HG.client_controller.services_manager.GetName( service_key )
            
            locations.add( name )
            
        
        for content_update in content_updates:
            
            ( data_type, action, row ) = content_update.ToTuple()
            
            if data_type == HC.CONTENT_TYPE_MAPPINGS:
                
                extra_words = ' tags for'
                
            
            actions.add( HC.content_update_string_lookup[ action ] )
            
            if action in ( HC.CONTENT_UPDATE_ARCHIVE, HC.CONTENT_UPDATE_INBOX ):
                
                locations = set()
                
            
            num_files += len( content_update.GetHashes() )
            
        
    
    s = ''
    
    if len( locations ) > 0:
        
        s += ', '.join( locations ) + '->'
        
    
    s += ', '.join( actions ) + extra_words + ' ' + HydrusData.ToHumanInt( num_files ) + ' files'
    
    return s
    
def ConvertServiceKeysToTagsToServiceKeysToContentUpdates( hashes, service_keys_to_tags ):
    
    service_keys_to_content_updates = {}
    
    for ( service_key, tags ) in service_keys_to_tags.items():
        
        if len( tags ) == 0:
            
            continue
            
        
        if service_key == CC.LOCAL_TAG_SERVICE_KEY:
            
            action = HC.CONTENT_UPDATE_ADD
            
        else:
            
            action = HC.CONTENT_UPDATE_PEND
            
        
        content_updates = [ HydrusData.ContentUpdate( HC.CONTENT_TYPE_MAPPINGS, action, ( tag, hashes ) ) for tag in tags ]
        
        service_keys_to_content_updates[ service_key ] = content_updates
        
    
    return service_keys_to_content_updates
    
def ConvertZoomToPercentage( zoom ):
    
    zoom_percent = zoom * 100
    
    pretty_zoom = '{:.2f}%'.format( zoom_percent )
    
    if pretty_zoom.endswith( '00%' ):
        
        pretty_zoom = '{:.0f}%'.format( zoom_percent )
        
    
    return pretty_zoom
    
def GetAlphaOfColour( colour, alpha ):
    
    ( r, g, b, a ) = colour.Get()
    
    return wx.Colour( r, g, b, alpha )
    
def GetDifferentLighterDarkerColour( colour, intensity = 3 ):
    
    ( r, g, b, a ) = colour.Get()
    
    if ColourIsGreyish( colour ):
        
        if ColourIsBright( colour ):
            
            colour = wx.Colour( int( g * ( 1 - 0.05 * intensity ) ), b, r )
            
        else:
            
            colour = wx.Colour( int( g * ( 1 + 0.05 * intensity ) / 2 ), b, r )
            
        
    else:
        
        colour = wx.Colour( g, b, r )
        
    
    return GetLighterDarkerColour( colour, intensity )
    
def GetLighterDarkerColour( colour, intensity = 3 ):
    
    if intensity is None or intensity == 0:
        
        return colour
        
    
    if ColourIsBright( colour ):
        
        return wx.lib.colourutils.AdjustColour( colour, -5 * intensity )
        
    else:
        
        ( r, g, b, a ) = colour.Get()
        
        ( r, g, b ) = [ max( value, 32 ) for value in ( r, g, b ) ]
        
        colour = wx.Colour( r, g, b )
        
        return wx.lib.colourutils.AdjustColour( colour, 5 * intensity )
    
def GetMediasTagCount( pool, tag_service_key = CC.COMBINED_TAG_SERVICE_KEY, collapse_siblings = False ):
    
    siblings_manager = HG.client_controller.tag_siblings_manager
    
    tags_managers = []
    
    for media in pool:
        
        if media.IsCollection():
            
            tags_managers.extend( media.GetSingletonsTagsManagers() )
            
        else:
            
            tags_managers.append( media.GetTagsManager() )
            
        
    
    current_tags_to_count = collections.Counter()
    deleted_tags_to_count = collections.Counter()
    pending_tags_to_count = collections.Counter()
    petitioned_tags_to_count = collections.Counter()
    
    for tags_manager in tags_managers:
        
        statuses_to_tags = tags_manager.GetStatusesToTags( tag_service_key )
        
        # combined is already collapsed
        if tag_service_key != CC.COMBINED_TAG_SERVICE_KEY and collapse_siblings:
            
            statuses_to_tags = siblings_manager.CollapseStatusesToTags( tag_service_key, statuses_to_tags )
            
        
        current_tags_to_count.update( statuses_to_tags[ HC.CONTENT_STATUS_CURRENT ] )
        deleted_tags_to_count.update( statuses_to_tags[ HC.CONTENT_STATUS_DELETED ] )
        pending_tags_to_count.update( statuses_to_tags[ HC.CONTENT_STATUS_PENDING ] )
        petitioned_tags_to_count.update( statuses_to_tags[ HC.CONTENT_STATUS_PETITIONED ] )
        
    
    return ( current_tags_to_count, deleted_tags_to_count, pending_tags_to_count, petitioned_tags_to_count )
    
def GetSortTypeChoices():

    sort_choices = list( CC.SORT_CHOICES )
    
    for ( namespaces_text, namespaces_list ) in HC.options[ 'sort_by' ]:
        
        sort_choices.append( ( namespaces_text, tuple( namespaces_list ) ) )
        
    
    service_keys = HG.client_controller.services_manager.GetServiceKeys( ( HC.LOCAL_RATING_LIKE, HC.LOCAL_RATING_NUMERICAL ) )
    
    for service_key in service_keys:
        
        sort_choices.append( ( 'rating', service_key ) )
        
    
    return sort_choices
    
def MergeCounts( min_a, max_a, min_b, max_b ):
    
    # 100-None and 100-None returns 100-200
    # 1-None and 4-5 returns 5-6
    # 1-2, and 5-7 returns 6, 9
    
    if min_a == 0:
        
        ( min_answer, max_answer ) = ( min_b, max_b )
        
    elif min_b == 0:
        
        ( min_answer, max_answer ) = ( min_a, max_a )
        
    else:
        
        if max_a is None:
            
            max_a = min_a
            
        
        if max_b is None:
            
            max_b = min_b
            
        
        min_answer = max( min_a, min_b )
        max_answer = max_a + max_b
        
    
    return ( min_answer, max_answer )
    
def MergePredicates( predicates, add_namespaceless = False ):
    
    master_predicate_dict = {}
    
    for predicate in predicates:
        
        # this works because predicate.__hash__ exists
        
        if predicate in master_predicate_dict:
            
            master_predicate_dict[ predicate ].AddCounts( predicate )
            
        else:
            
            master_predicate_dict[ predicate ] = predicate
            
        
    
    if add_namespaceless:
        
        # we want to include the count for namespaced tags in the namespaceless version when:
        # there exists more than one instance of the subtag with different namespaces, including '', that has nonzero count
        
        unnamespaced_predicate_dict = {}
        subtag_nonzero_instance_counter = collections.Counter()
        
        for predicate in list(master_predicate_dict.values()):
            
            if predicate.HasNonZeroCount():
                
                unnamespaced_predicate = predicate.GetUnnamespacedCopy()
                
                subtag_nonzero_instance_counter[ unnamespaced_predicate ] += 1
                
                if unnamespaced_predicate in unnamespaced_predicate_dict:
                    
                    unnamespaced_predicate_dict[ unnamespaced_predicate ].AddCounts( unnamespaced_predicate )
                    
                else:
                    
                    unnamespaced_predicate_dict[ unnamespaced_predicate ] = unnamespaced_predicate
                    
                
            
        
        for ( unnamespaced_predicate, count ) in list(subtag_nonzero_instance_counter.items()):
            
            # if there were indeed several instances of this subtag, overwrte the master dict's instance with our new count total
            
            if count > 1:
                
                master_predicate_dict[ unnamespaced_predicate ] = unnamespaced_predicate_dict[ unnamespaced_predicate ]
                
            
        
    
    return list(master_predicate_dict.values())
    
def OrdIsSensibleASCII( o ):
    
    return 32 <= o and o <= 127
    
def OrdIsAlphaLower( o ):
    
    return 97 <= o and o <= 122
    
def OrdIsAlphaUpper( o ):
    
    return 65 <= o and o <= 90
    
def OrdIsAlpha( o ):
    
    return OrdIsAlphaLower( o ) or OrdIsAlphaUpper( o )
    
def OrdIsNumber( o ):
    
    return 48 <= o and o <= 57
    
def ReportShutdownException():
    
    text = 'A serious error occurred while trying to exit the program. Its traceback may be shown next. It should have also been written to client.log. You may need to quit the program from task manager.'
    
    HydrusData.DebugPrint( text )
    
    HydrusData.DebugPrint( traceback.format_exc() )
    
    wx.SafeShowMessage( 'shutdown error', text )
    wx.SafeShowMessage( 'shutdown error', traceback.format_exc() )
    
def ShowExceptionClient( e, do_wait = True ):
    
    ( etype, value, tb ) = sys.exc_info()
    
    if etype is None:
        
        etype = type( e )
        value = str( e )
        
        trace = 'No error trace--here is the stack:' + os.linesep + ''.join( traceback.format_stack() )
        
    else:
        
        trace = ''.join( traceback.format_exception( etype, value, tb ) )
        
    
    pretty_value = str( value )
    
    if os.linesep in pretty_value:
        
        ( first_line, anything_else ) = pretty_value.split( os.linesep, 1 )
        
        trace = trace + os.linesep + anything_else
        
    else:
        
        first_line = pretty_value
        
    
    job_key = ClientThreading.JobKey()
    
    if isinstance( e, HydrusExceptions.ShutdownException ):
        
        return
        
    else:
        
        if hasattr( etype, '__name__' ):
            
            title = str( etype.__name__ )
            
        else:
            
            title = str( etype )
            
        
        job_key.SetVariable( 'popup_title', title )
        
        job_key.SetVariable( 'popup_text_1', first_line )
        job_key.SetVariable( 'popup_traceback', trace )
        
    
    text = job_key.ToString()
    
    HydrusData.Print( 'Exception:' )
    
    HydrusData.DebugPrint( text )
    
    HG.client_controller.pub( 'message', job_key )
    
    if do_wait:
        
        time.sleep( 1 )
    
def ShowTextClient( text ):
    
    job_key = ClientThreading.JobKey()
    
    job_key.SetVariable( 'popup_text_1', str( text ) )
    
    text = job_key.ToString()
    
    HydrusData.Print( text )
    
    HG.client_controller.pub( 'message', job_key )
  

### CLASSES ###    
class HydrusYAMLBase( yaml.YAMLObject ):
    
    yaml_loader = yaml.SafeLoader
    yaml_dumper = yaml.SafeDumper
    
class AccountIdentifier( HydrusSerialisable.SerialisableBase ):
    
    SERIALISABLE_TYPE = HydrusSerialisable.SERIALISABLE_TYPE_ACCOUNT_IDENTIFIER
    SERIALISABLE_NAME = 'Account Identifier'
    SERIALISABLE_VERSION = 1
    
    TYPE_ACCOUNT_KEY = 1
    TYPE_CONTENT = 2
    
    def __init__( self, account_key = None, content = None ):
        
        HydrusYAMLBase.__init__( self )
        
        if account_key is not None:
            
            self._type = self.TYPE_ACCOUNT_KEY
            self._data = account_key
            
        elif content is not None:
            
            self._type = self.TYPE_CONTENT
            self._data = content
            
        
    
    def __eq__( self, other ): return self.__hash__() == other.__hash__()
    
    def __hash__( self ): return ( self._type, self._data ).__hash__()
    
    def __ne__( self, other ): return self.__hash__() != other.__hash__()
    
    def __repr__( self ): return 'Account Identifier: ' + str( ( self._type, self._data ) )
    
    def _GetSerialisableInfo( self ):
        
        if self._type == self.TYPE_ACCOUNT_KEY:
            
            serialisable_data = self._data.hex()
            
        elif self._type == self.TYPE_CONTENT:
            
            serialisable_data = self._data.GetSerialisableTuple()
            
        
        return ( self._type, serialisable_data )
        
    
    def _InitialiseFromSerialisableInfo( self, serialisable_info ):
        
        ( self._type, serialisable_data ) = serialisable_info
        
        if self._type == self.TYPE_ACCOUNT_KEY:
            
            self._data = bytes.fromhex( serialisable_data )
            
        elif self._type == self.TYPE_CONTENT:
            
            self._data = HydrusSerialisable.CreateFromSerialisableTuple( serialisable_data )
            
        
    
    def GetData( self ): return self._data
    
    def HasAccountKey( self ): return self._type == self.TYPE_ACCOUNT_KEY
    
    def HasContent( self ): return self._type == self.TYPE_CONTENT
    
HydrusSerialisable.SERIALISABLE_TYPES_TO_OBJECT_TYPES[ HydrusSerialisable.SERIALISABLE_TYPE_ACCOUNT_IDENTIFIER ] = AccountIdentifier

class AccountType( HydrusYAMLBase ):
    
    yaml_tag = '!AccountType'
    
    def __init__( self, title, permissions, max_monthly_data ):
        
        HydrusYAMLBase.__init__( self )
        
        self._title = title
        self._permissions = permissions
        self._max_monthly_data = max_monthly_data
        
    
    def __repr__( self ): return self.ConvertToString()
    
    def GetPermissions( self ): return self._permissions
    
    def GetTitle( self ): return self._title
    
    def GetMaxBytes( self ):
        
        ( max_num_bytes, max_num_requests ) = self._max_monthly_data
        
        return max_num_bytes
        
    
    def GetMaxRequests( self ):
        
        ( max_num_bytes, max_num_requests ) = self._max_monthly_data
        
        return max_num_requests
        
    
    def GetMaxBytesString( self ):
        
        ( max_num_bytes, max_num_requests ) = self._max_monthly_data
        
        if max_num_bytes is None: max_num_bytes_string = 'No limit'
        else: max_num_bytes_string = ToHumanBytes( max_num_bytes )
        
        return max_num_bytes_string
        
    
    def GetMaxRequestsString( self ):
        
        ( max_num_bytes, max_num_requests ) = self._max_monthly_data
        
        if max_num_requests is None: max_num_requests_string = 'No limit'
        else: max_num_requests_string = ToHumanInt( max_num_requests )
        
        return max_num_requests_string
        
    
    def ConvertToString( self ):
        
        result_string = self._title + ' with '
        
        if self._permissions == [ HC.UNKNOWN_PERMISSION ]: result_string += 'no permissions'
        else: result_string += ', '.join( [ HC.permissions_string_lookup[ permission ] for permission in self._permissions ] ) + ' permissions'
        
        return result_string
        
    
    def IsUnknownAccountType( self ): return self._permissions == [ HC.UNKNOWN_PERMISSION ]
    
    def HasPermission( self, permission ): return permission in self._permissions
    
sqlite3.register_adapter( AccountType, yaml.safe_dump )

class BigJobPauser( object ):
    
    def __init__( self, period = 10, wait_time = 0.1 ):
        
        self._period = period
        self._wait_time = wait_time
        
        self._next_pause = GetNow() + self._period
        
    
    def Pause( self ):
        
        if TimeHasPassed( self._next_pause ):
            
            time.sleep( self._wait_time )
            
            self._next_pause = GetNow() + self._period
    
class Call( object ):
    
    def __init__( self, func, *args, **kwargs ):
        
        self._func = func
        self._args = args
        self._kwargs = kwargs
        
    
    def __call__( self ):
        
        self._func( *self._args, **self._kwargs )
        
    
    def __repr__( self ):
        
        return 'Call: ' + repr( ( self._func, self._args, self._kwargs ) )
    
class ContentUpdate( object ):
    
    def __init__( self, data_type, action, row, reason = None ):
        
        self._data_type = data_type
        self._action = action
        self._row = row
        self._reason = reason
        
    
    def __eq__( self, other ):
        
        return hash( self ) == hash( other )
        
    
    def __ne__( self, other ): return not self.__eq__( other )
    
    def __hash__( self ):
        
        return hash( ( self._data_type, self._action, repr( self._row ) ) )
        
    
    def __repr__( self ):
        
        return 'Content Update: ' + str( ( self._data_type, self._action, self._row ) )
        
    
    def GetAction( self ):
        
        return self._action
        
    
    def GetDataType( self ):
        
        return self._data_type
        
    
    def GetHashes( self ):
        
        if self._data_type == HC.CONTENT_TYPE_FILES:
            
            if self._action == HC.CONTENT_UPDATE_ADVANCED:
                
                hashes = set()
                
            elif self._action == HC.CONTENT_UPDATE_ADD:
                
                ( file_info_manager, timestamp ) = self._row
                
                hashes = { file_info_manager.hash }
                
            else:
                
                hashes = self._row
                
            
        elif self._data_type == HC.CONTENT_TYPE_DIRECTORIES:
            
            hashes = set()
            
        elif self._data_type == HC.CONTENT_TYPE_URLS:
            
            ( urls, hashes ) = self._row
            
        elif self._data_type == HC.CONTENT_TYPE_MAPPINGS:
            
            if self._action == HC.CONTENT_UPDATE_ADVANCED:
                
                hashes = set()
                
            else:
                
                ( tag, hashes ) = self._row
                
            
        elif self._data_type in ( HC.CONTENT_TYPE_TAG_PARENTS, HC.CONTENT_TYPE_TAG_SIBLINGS ):
            
            hashes = set()
            
        elif self._data_type == HC.CONTENT_TYPE_RATINGS:
            
            if self._action == HC.CONTENT_UPDATE_ADD:
                
                ( rating, hashes ) = self._row
                
            
        elif self._data_type == HC.CONTENT_TYPE_NOTES:
            
            if self._action == HC.CONTENT_UPDATE_SET:
                
                ( notes, hash ) = self._row
                
                hashes = { hash }
                
            
        elif self._data_type == HC.CONTENT_TYPE_FILE_VIEWING_STATS:
            
            ( hash, preview_views_delta, preview_viewtime_delta, media_views_delta, media_viewtime_delta ) = self._row
            
            hashes = { hash }
            
        
        if not isinstance( hashes, set ):
            
            hashes = set( hashes )
            
        
        return hashes
        
    
    def GetReason( self ):
        
        if self._reason is None:
            
            return 'No reason given.'
            
        else:
            
            return self._reason
            
        
    
    def GetWeight( self ):
        
        return len( self.GetHashes() )
        
    
    def IsInboxRelated( self ):
        
        return self._action in ( HC.CONTENT_UPDATE_ARCHIVE, HC.CONTENT_UPDATE_INBOX )
        
    
    def ToTuple( self ):
        
        return ( self._data_type, self._action, self._row )
    
class JobDatabase( object ):
    
    def __init__( self, job_type, synchronous, action, *args, **kwargs ):
        
        self._type = job_type
        self._synchronous = synchronous
        self._action = action
        self._args = args
        self._kwargs = kwargs
        
        self._result_ready = threading.Event()
        
    
    def GetCallableTuple( self ):
        
        return ( self._action, self._args, self._kwargs )
        
    
    def GetResult( self ):
        
        time.sleep( 0.00001 ) # this one neat trick can save hassle on superquick jobs as event.wait can be laggy
        
        while True:
            
            if self._result_ready.wait( 2 ) == True:
                
                break
                
            elif HG.model_shutdown:
                
                raise HydrusExceptions.ShutdownException( 'Application quit before db could serve result!' )
                
            
        
        if isinstance( self._result, Exception ):
            
            e = self._result
            
            raise e
            
        else:
            
            return self._result
            
        
    
    def GetType( self ):
        
        return self._type
        
    
    def IsSynchronous( self ):
        
        return self._synchronous
        
    
    def PutResult( self, result ):
        
        self._result = result
        
        self._result_ready.set()
        
    
    def ToString( self ):
        
        return self._type + ' ' + self._action
    
class ServiceUpdate( object ):
    
    def __init__( self, action, row = None ):
        
        self._action = action
        self._row = row
        
    
    def ToTuple( self ):
        
        return ( self._action, self._row )
        
### CLIENT CLASSES ###    
class ApplicationCommand( HydrusSerialisable.SerialisableBase ):
    
    SERIALISABLE_TYPE = HydrusSerialisable.SERIALISABLE_TYPE_APPLICATION_COMMAND
    SERIALISABLE_NAME = 'Application Command'
    SERIALISABLE_VERSION = 1
    
    def __init__( self, command_type = None, data = None ):
        
        if command_type is None:
            
            command_type = CC.APPLICATION_COMMAND_TYPE_SIMPLE
            
        
        if data is None:
            
            data = 'archive_file'
            
        
        HydrusSerialisable.SerialisableBase.__init__( self )
        
        self._command_type = command_type
        self._data = data
        
    
    def __repr__( self ):
        
        return self.ToString()
        
    
    def _GetSerialisableInfo( self ):
        
        if self._command_type == CC.APPLICATION_COMMAND_TYPE_SIMPLE:
            
            serialisable_data = self._data
            
        elif self._command_type == CC.APPLICATION_COMMAND_TYPE_CONTENT:
            
            ( service_key, content_type, action, value ) = self._data
            
            serialisable_data = ( service_key.hex(), content_type, action, value )
            
        
        return ( self._command_type, serialisable_data )
        
    
    def _InitialiseFromSerialisableInfo( self, serialisable_info ):
        
        ( self._command_type, serialisable_data ) = serialisable_info
        
        if self._command_type == CC.APPLICATION_COMMAND_TYPE_SIMPLE:
            
            self._data = serialisable_data
            
        elif self._command_type == CC.APPLICATION_COMMAND_TYPE_CONTENT:
            
            ( serialisable_service_key, content_type, action, value ) = serialisable_data
            
            self._data = ( bytes.fromhex( serialisable_service_key ), content_type, action, value )
            
        
    
    def GetCommandType( self ):
        
        return self._command_type
        
    
    def GetData( self ):
        
        return self._data
        
    
    def ToString( self ):
        
        if self._command_type == CC.APPLICATION_COMMAND_TYPE_SIMPLE:
            
            return self._data
            
        elif self._command_type == CC.APPLICATION_COMMAND_TYPE_CONTENT:
            
            ( service_key, content_type, action, value ) = self._data
            
            components = []
            
            components.append( HC.content_update_string_lookup[ action ] )
            components.append( HC.content_type_string_lookup[ content_type ] )
            components.append( '"' + str( value ) + '"' )
            components.append( 'for' )
            
            services_manager = HG.client_controller.services_manager
            
            if services_manager.ServiceExists( service_key ):
                
                service = services_manager.GetService( service_key )
                
                components.append( service.GetName() )
                
            else:
                
                components.append( 'unknown service!' )
                
            
            return ' '.join( components )
            
HydrusSerialisable.SERIALISABLE_TYPES_TO_OBJECT_TYPES[ HydrusSerialisable.SERIALISABLE_TYPE_APPLICATION_COMMAND ] = ApplicationCommand

class Booru( HydrusData.HydrusYAMLBase ):
    
    yaml_tag = '!Booru'
    
    def __init__( self, name, search_url, search_separator, advance_by_page_num, thumb_classname, image_id, image_data, tag_classnames_to_namespaces ):
        
        self._name = name
        self._search_url = search_url
        self._search_separator = search_separator
        self._advance_by_page_num = advance_by_page_num
        self._thumb_classname = thumb_classname
        self._image_id = image_id
        self._image_data = image_data
        self._tag_classnames_to_namespaces = tag_classnames_to_namespaces
        
    
    def GetData( self ): return ( self._search_url, self._search_separator, self._advance_by_page_num, self._thumb_classname, self._image_id, self._image_data, self._tag_classnames_to_namespaces )
    
    def GetGalleryParsingInfo( self ): return ( self._search_url, self._advance_by_page_num, self._search_separator, self._thumb_classname )
    
    def GetName( self ): return self._name
    
    def GetNamespaces( self ): return list(self._tag_classnames_to_namespaces.values())
    
sqlite3.register_adapter( Booru, yaml.safe_dump )

class Credentials( HydrusData.HydrusYAMLBase ):
    
    yaml_tag = '!Credentials'
    
    def __init__( self, host, port, access_key = None ):
        
        HydrusData.HydrusYAMLBase.__init__( self )
        
        if host == 'localhost':
            
            host = '127.0.0.1'
            
        
        self._host = host
        self._port = port
        self._access_key = access_key
        
    
    def __eq__( self, other ): return self.__hash__() == other.__hash__()
    
    def __hash__( self ): return ( self._host, self._port, self._access_key ).__hash__()
    
    def __ne__( self, other ): return self.__hash__() != other.__hash__()
    
    def __repr__( self ): return 'Credentials: ' + str( ( self._host, self._port, self._access_key.hex() ) )
    
    def GetAccessKey( self ): return self._access_key
    
    def GetAddress( self ): return ( self._host, self._port )
    
    def GetConnectionString( self ):
        
        connection_string = ''
        
        if self.HasAccessKey(): connection_string += self._access_key.hex() + '@'
        
        connection_string += self._host + ':' + str( self._port )
        
        return connection_string
        
    
    def HasAccessKey( self ): return self._access_key is not None and self._access_key is not ''
    
    def SetAccessKey( self, access_key ): self._access_key = access_key
    
class Imageboard( HydrusData.HydrusYAMLBase ):
    
    yaml_tag = '!Imageboard'
    
    def __init__( self, name, post_url, flood_time, form_fields, restrictions ):
        
        self._name = name
        self._post_url = post_url
        self._flood_time = flood_time
        self._form_fields = form_fields
        self._restrictions = restrictions
        
    
    def IsOKToPost( self, media_result ):
        
        # deleted old code due to deprecation
        
        return True
        
    
    def GetBoardInfo( self ): return ( self._post_url, self._flood_time, self._form_fields, self._restrictions )
    
    def GetName( self ): return self._name
    
sqlite3.register_adapter( Imageboard, yaml.safe_dump )