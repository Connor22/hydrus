### IMPORTS ###
from lib.Client import ImageHandling

from lib.Hydrus import Constants as HC

import collections, os, unittest

### CODE ###
class TestImageHandling( unittest.TestCase ):
    
    def test_phash( self ):
        
        phashes = ImageHandling.GenerateShapePerceptualHashes( os.path.join( HC.STATIC_DIR, 'hydrus.png' ), HC.IMAGE_PNG )
        
        self.assertEqual( phashes, set( [ b'\xb4M\xc7\xb2M\xcb8\x1c' ] ) )
        
