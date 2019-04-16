from tkinter import filedialog
from tkinter import *
from osgeo import gdal
from osgeo import gdal_array
import gdal
from osgeo import gdal, gdalnumeric, ogr, osr
from arsf_envi_reader import envi_header
from PIL import Image
from PIL import ImageDraw
from functools import reduce
import operator
import os
import subprocess
import sys
gdal.UseExceptions()
gdal.SetConfigOption('GDAL_ARRAY_OPEN_BY_FILENAME', 'TRUE')

def show_entry_fields():
    entryfields = "Path to DSM: " + e1.get() + "\nPath to AOI: " + e2.get() + "\nOutput: " + e3.get()
    return entryfields


# This function will convert the rasterized clipper shapefile
# to a mask for use within GDAL.
def imageToArray(i):
    """
    Converts a Python Imaging Library array to a
    gdalnumeric image.
    """
    a=gdalnumeric.fromstring(i.tobytes(),'b')
    a.shape=i.im.size[1], i.im.size[0]
    return a

def arrayToImage(a):
    """
    Converts a gdalnumeric array to a
    Python Imaging Library Image.
    """
    i=Image.frombytes('L',(a.shape[1],a.shape[0]),
            (a.astype('b')).tobytes())
    return i

def world2Pixel(geoMatrix, x, y):
  """
  Uses a gdal geomatrix (gdal.GetGeoTransform()) to calculate
  the pixel location of a geospatial coordinate
  """
  ulX = geoMatrix[0]
  ulY = geoMatrix[3]
  xDist = geoMatrix[1]
  yDist = geoMatrix[5]
  rtnX = geoMatrix[2]
  rtnY = geoMatrix[4]
  pixel = int((x - ulX) / xDist)
  line = int((ulY - y) / xDist)
  return (pixel, line)

#
#  EDIT: this is basically an overloaded
#  version of the gdal_array.OpenArray passing in xoff, yoff explicitly
#  so we can pass these params off to CopyDatasetInfo
#
def OpenArray( array, prototype_ds = None, xoff=0, yoff=0 ):
    ds = gdal.Open( gdalnumeric.GetArrayFilename(array) )

    if ds is not None and prototype_ds is not None:
        if type(prototype_ds).__name__ == 'str':
            prototype_ds = gdal.Open( prototype_ds )
        if prototype_ds is not None:
            gdalnumeric.CopyDatasetInfo( prototype_ds, ds, xoff=xoff, yoff=yoff )
    return ds

def histogram(a, bins=range(0,256)):
  """
  Histogram function for multi-dimensional array.
  a = array
  bins = range of numbers to match
  """
  fa = a.flat
  n = gdalnumeric.searchsorted(gdalnumeric.sort(fa), bins)
  n = gdalnumeric.concatenate([n, [len(fa)]])
  hist = n[1:]-n[:-1]
  return hist

def stretch(a):
  """
  Performs a histogram stretch on a gdalnumeric array image.
  """
  hist = histogram(a)
  im = arrayToImage(a)
  lut = []
  for b in range(0, len(hist), 256):
    # step size
    step = reduce(operator.add, hist[b:b+256]) / 255
    # create equalization lookup table
    n = 0
    for i in range(256):
      lut.append(n / step)
      n = n + hist[i+b]
  im = im.point(lut)
  return imageToArray(im)

def clip( shapefile_path, raster_path ):
    # Load the source data as a gdalnumeric array
    srcArray = gdalnumeric.LoadFile(raster_path)

    # Also load as a gdal image to get geotransform
    # (world file) info
    srcImage = gdal.Open(raster_path)
    geoTrans = srcImage.GetGeoTransform()

    #check for kml drivers
    extension = shapefile_path.split('.')[1]
    if (extension == "kml"):
        driver = ogr.GetDriverByName('KML')
        dataSource = driver.Open(shapefile_path)
        lyr=dataSource.GetLayer()
    else:
        shapef = ogr.Open(shapefile_path)
        lyr = shapef.GetLayer( os.path.split( os.path.splitext( shapefile_path )[0] )[1] )
    poly = lyr.GetNextFeature()

    # Convert the layer extent to image pixel coordinates
    minX, maxX, minY, maxY = lyr.GetExtent()
    ulX, ulY = world2Pixel(geoTrans, minX, maxY)
    lrX, lrY = world2Pixel(geoTrans, maxX, minY)

    # Calculate the pixel size of the new image
    pxWidth = int(lrX - ulX)
    pxHeight = int(lrY - ulY)

    clip = srcArray[ulY:lrY, ulX:lrX]

    #
    # EDIT: create pixel offset to pass to new image Projection info
    #
    xoffset =  ulX
    yoffset =  ulY
    print("Xoffset, Yoffset = ( %f, %f )" % ( xoffset, yoffset ))

    # Create a new geomatrix for the image
    geoTrans = list(geoTrans)
    geoTrans[0] = minX
    geoTrans[3] = maxY

    # Map points to pixels for drawing the
    # boundary on a blank 8-bit,
    # black and white, mask image.
    points = []
    pixels = []
    geom = poly.GetGeometryRef()
    pts = geom.GetGeometryRef(0)
    for p in range(pts.GetPointCount()):
      points.append((pts.GetX(p), pts.GetY(p)))
    for p in points:
      pixels.append(world2Pixel(geoTrans, p[0], p[1]))
    rasterPoly = Image.new("L", (pxWidth, pxHeight), 1)
    rasterize = ImageDraw.Draw(rasterPoly)
    rasterize.polygon(pixels, 0)
    mask = imageToArray(rasterPoly)
    # Clip the image using the mask
    clip = gdalnumeric.choose(mask, \
        (clip, 0)).astype(gdalnumeric.uint8)

    # This image has 3 bands so we stretch each one to make them
    # visually brighter
    for i in range(3):
      clip[:,:] = stretch(clip[:,:])

    # Save new tiff
    #
    #  EDIT: instead of SaveArray, let's break all the
    #  SaveArray steps out more explicity so
    #  we can overwrite the offset of the destination
    #  raster
    #
    ### the old way using SaveArray
    #
    # gdalnumeric.SaveArray(clip, "OUTPUT.tif", format="GTiff", prototype=raster_path)
    #
    ###
    #
    gtiffDriver = gdal.GetDriverByName( 'GTiff' )
    if gtiffDriver is None:
        raise ValueError("Can't find GeoTiff Driver")
    output_path = ""
    output_path = e3.get() + "/OUTPUT.tif"
    gtiffDriver.CreateCopy( output_path,
        OpenArray( clip, prototype_ds=raster_path, xoff=xoffset, yoff=yoffset )
    )

    # Save as an 8-bit jpeg for an easy, quick preview
    clip = clip.astype(gdalnumeric.uint8)
    output_path = ""
    output_path = e3.get() + "/OUTPUT.jpg"
    gdalnumeric.SaveArray(clip, output_path, format="JPEG")
    exportBIL()
    gdal.ErrorReset()


def entry1():
    targetfile = getpath("D:/'PlacementProjects/TerrainData/mygeodata")
    e1.insert(0, targetfile)


def entry2():
    targetfile = getpath("D:/'PlacementProjects/TerrainData/DSM/Ireland_DSM")
    e2.insert(0, targetfile)
    #shpArr = imagetoarray(i)


def entry3():
    targetfile = getOutputPath("D:/'PlacementProjects/TerrainData/mygeodata")
    e3.insert(0, targetfile)



def getpath(dir):
    window.filename = filedialog.askopenfilename(initialdir=dir, title="Select file")
    return window.filename


def getOutputPath(dir):
    window.directory = filedialog.askdirectory(initialdir=dir, title="Select Output Directory")
    return window.directory


def loadgeotiff(path):
    gtif = gdal.Open(path)
    return gtif


def generateoutput():
    clip(e1.get(), e2.get())


def exportBIL():
        subprocess.run(["D:/PlacementProjects/TerrainData/GDAL_GeoTIFF_2_BIL.bat", "D:/PlacementProjects/TerrainData/output/OUTPUT.tif", "D:/PlacementProjects/TerrainData/output/OUTPUT.bil"])





window = Tk()
window.title("Terrain Generator")
# Column Position
cp = 1

#
Label(window, text="Shapefile").grid(row=0, column=cp)
Label(window, text="DSM").grid(row=1, column=cp)
Label(window, text="Output Path").grid(row=2, column=cp)

#
e1 = Entry(window, width=60)
e2 = Entry(window, width=60)
e3 = Entry(window, width=60)

cp += 1

#
e1.grid(row=0, column=cp)
e2.grid(row=1, column=cp)
e3.grid(row=2, column=cp)

#
b1 = Button(window, text="...", command=entry1).grid(row=0, column=3, padx=(0, 30))
b2 = Button(window, text="...", command=entry2).grid(row=1, column=3, padx=(0, 30))
b3 = Button(window, text="...", command=entry3).grid(row=2, column=3, padx=(0, 30))

#
Button(window, text='Quit', command=window.quit).grid(row=3, column=0, sticky=W, pady=4)
Button(window, text='Generate Output', command=generateoutput).grid(row=3, column=1, sticky=W, pady=4)

mainloop()
