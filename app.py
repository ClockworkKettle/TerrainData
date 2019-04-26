from tkinter import filedialog
from tkinter import *
import tkinter as tk
from osgeo import gdal
from osgeo import gdal_array
import gdal
#from osgeo import gdal, gdalnumeric, ogr, osr
from arsf_envi_reader import envi_header
from PIL import Image
from PIL import ImageDraw
from functools import reduce
import operator
import os
import subprocess
import sys
import json

gdal.UseExceptions()
gdal.SetConfigOption('GDAL_ARRAY_OPEN_BY_FILENAME', 'TRUE')

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
    print("ulx: ", ulX, "\tulY: ", ulY, "\tlrx: ", lrX, "\tlry: ", lrY)
    print("minX: ", minX, "\tmaxX: ", maxX, "\tminY: ", minY, "\tmaxY: ", maxY)
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
        (clip, 0))

    # Save new tiff
    #
    #  EDIT: instead of SaveArray, let's break all the
    #  SaveArray steps out more explicity so
    #  we can overwrite the offset of the destination
    #  raster
    #
    gtiffDriver = gdal.GetDriverByName( 'GTiff' )
    if gtiffDriver is None:
        raise ValueError("Can't find GeoTiff Driver")
    output_path = ""
    output_path = app.e3.get() + "/OUTPUT.tif"
    gtiffDriver.CreateCopy( output_path,
        OpenArray( clip, prototype_ds=raster_path, xoff=xoffset, yoff=yoffset )
    )

    # Save as an 8-bit jpeg for an easy, quick preview
    clip = clip.astype(gdalnumeric.uint8)
    output_path = ""
    output_path = app.e3.get() + "/OUTPUT.jpg"
    gdalnumeric.SaveArray(clip, output_path, format="JPEG")
    exportBIL()
    gdal.ErrorReset()

def loadgeotiff(path):
    gtif = gdal.Open(path)
    return gtif

def exportBIL():
        subprocess.run(["GDAL_GeoTIFF_2_BIL.bat", "OUTPUT/OUTPUT.tif", "OUTPUT/OUTPUT.bil"])


class mainWindow:
    def __init__(self, master):

        self.master = master
        self.master.title("DSM Converter")
        self.frame = tk.Frame(self.master)
        #
        Label(self.frame, text="Shapefile/Kml").grid(row=0, column=1)
        self.e1 = Entry(self.frame, width=60)
        self.e1.grid(row=0, column=2, pady=(50,50))
        self.e1.insert(0, conf.getConfigKeyValue('e1'))

        self.b1 = Button(self.frame, text="...", command=self.entry1Button).grid(row=0, column=3, padx=(0, 30))
        self.b2 = Button(self.frame, text="Settings", command=self.settings_window).grid (row=3, column=3, padx=(0,30))
        #
        Button(self.frame, text='Quit', command=self.frame.quit).grid(row=3, column=0, sticky=W, pady=4, padx=(20,0))
        Button(self.frame, text='Generate Output', command=self.generateOutput_button).grid(row=3, column=1, sticky=W, pady=4)

        self.frame.pack()
        print("Initialize Main Window Complete")

    def settings_window(self):
        self.newWindow = tk.Toplevel(self.master)
        self.app=settingsWindow(self.newWindow)

    def entry1Button(self):
        targetfile = self.getFilePath()
        self.e1.delete(0,'end')
        self.e1.insert(0, targetfile)
        conf.writeConfigData('e1', targetfile)

    def generateOutput_button(self):
        clip(self.e1.get(), self.e2.get())

    def getFilePath(self):
        self.filename = filedialog.askopenfilename(initialdir="", title="Select file")
        return self.filename

    def getFolderPath(self):
        self.directory = filedialog.askdirectory(initialdir="", title="Select Output Directory")
        return self.directory


class settingsWindow:
    def __init__(self, master):
        self.master = master
        self.master.title("Settings")
        self.frame = tk.Frame(self.master)
        self.frame.grab_set()

        Label(self.frame, text="DSM").grid(row=0, column=1)
        Label(self.frame, text="Output Path").grid(row=1, column=1)

        self.e2 = Entry(self.frame, width=60)
        self.e3 = Entry(self.frame, width=60)

        self.e2.grid(row=0, column=2)
        self.e3.grid(row=1, column=2)

        self.e2.insert(0, conf.getConfigKeyValue('e2'))
        self.e3.insert(0, conf.getConfigKeyValue('e3'))

        self.b2 = Button(self.frame, text="...", command=self.entry2Button).grid(row=0, column=3, padx=(0, 30))
        self.b3 = Button(self.frame, text="...", command=self.entry3Button).grid(row=1, column=3, padx=(0, 30))

        self.sb2 = Button (self.frame, text="Reset Config", command=conf.reinit_config).grid(row=3, column=2)

        self.sbExit = Button(self.frame, text="ok", command=self.settingsExit).grid(row=4, column=3, padx=(20,20), pady=(0,10) )
        self.frame.pack()
        print("Initialization complete")

    def entry2Button(self):
        targetfile = self.getFilePath()
        self.e2.delete(0,'end')
        self.e2.insert(0, targetfile)
        conf.writeConfigData('e2', targetfile)

    def entry3Button(self):
        targetfile = self.getFolderPath()
        self.e3.delete(0,'end')
        self.e3.insert(0, targetfile)
        conf.writeConfigData('e3', targetfile)

    def settingsExit(self):
        self.master.destroy()
        print("settings quit")


class config:
    def __init__(self):
        file_path = 'config.json'
        try:
            with open(file_path) as json_file:
                data = json.load(json_file)
        except IOError:
            # If there is no config ile, create one
            data = open(file_path, 'w+')
            data.write('{\n\t"e1":"",\n\t"e2":"",\n\t"e3":"",\n\t"gdal":""\n}')
            with open(file_path) as json_file:
                data = json.load(json_file)

        self.configdata = data

    def getConfigData(self):
        return self.configdata

    def getConfigKeyValue(self, key):
        return self.configdata[key]

    def writeConfigData(self,key,value):
        self.configdata[key] = value
        with open("config.json", "w") as write_file:
            json.dump(self.configdata, write_file)
        print(self.configdata)

    def reinit_config(self):
        file_path = 'config.json'
        data = open(file_path, 'w+')
        data.write('{\n\t"e1":"",\n\t"e2":"",\n\t"e3":"",\n\t"gdal":""\n}')
        #with open(file_path) as json_file:
        #    data = json.load(json_file)
        #self.configdata = data


def main():
    global conf
    conf = config()
    root = tk.Tk()
    global app
    app = mainWindow(root)
    root.mainloop()

if __name__ == '__main__':
    main()
