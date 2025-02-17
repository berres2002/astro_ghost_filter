from __future__ import print_function
import numpy as np
from astropy.table import Table
from PIL import Image
from io import BytesIO
import os
import pandas as pd
from astropy.io import fits
from astropy.visualization import PercentileInterval, AsinhStretch
from astropy.io import ascii
from astropy.table import Table
import sys
import re
import json
import mastcasjobs
import requests
from datetime import datetime
from astropy import units as u
from astropy.coordinates import Angle
try: # Python 3.x
    from urllib.parse import quote as urlencode
    from urllib.request import urlretrieve
except ImportError:  # Python 2.x
    from urllib import pathname2url as urlencode
    from urllib import urlretrieve
try: # Python 3.x
    import http.client as httplib
except ImportError:  # Python 2.x
    import httplib
# std lib
from collections import OrderedDict
from os import listdir
from os.path import isfile, join
# 3rd party
from astropy import utils, io, convolution, wcs
from astropy.visualization import make_lupton_rgb
from astropy.coordinates import name_resolve
from pyvo.dal import sia
import pickle
from io import BytesIO

from astropy.coordinates import SkyCoord
from astroquery.vo_conesearch import ConeSearch
from astroquery.vo_conesearch import vos_catalog
vos_catalog.list_catalogs("conesearch_good")
from warnings import simplefilter

#could absolutely be more efficient, but filter for now 
simplefilter(action="ignore", category=pd.errors.PerformanceWarning)

#set environmental variables
if "CASJOBS_USERID" not in os.environ:
    os.environ['CASJOBS_USERID'] = 'ghostbot'
    os.environ['CASJOBS_PW'] = 'ghostbot'

def getAllPostageStamps(df, tempSize, path=".", verbose=0):
    for i in np.arange(len(df["raMean"])):
            tempRA = df.loc[i, 'raMean']
            tempDEC = df.loc[i, 'decMean']
            tempName = df.loc[i, 'TransientName']
            a = find_all(path+"/%s.png" % tempName, path)
            if not a:
                try:
                    img = getcolorim(tempRA, tempDEC, size=tempSize, filters="grizy", format="png")
                    img.save(path+"/%s.png" % tempName)
                    if verbose:
                        print("Saving postage stamp for the host of %s."% tempName)
                except:
                    continue

def preview_image(i, ra, dec, rad, band, save=1):
    a = find_all("PS1_ra={}_dec={}_{}arcsec_{}.fits".format(ra, dec, rad, band), ".")
    hdul = fits.open(a[0])
    image_file = get_pkg_data_filename(a[0])
    image_data = fits.getdata(image_file, ext=0)
    plt.figure()
    plt.imshow(image_data,cmap='viridis')
    plt.axis('off')
    #plt.colorbar()
    if save:
        plt.savefig("PS1_%i_%s.png" % (i, band))

def get_hosts(path, transient_fn, fn_Host, rad):
    transient_df = pd.read_csv(path+"/"+transient_fn)
    now = datetime.now()
    dict_fn = fn_Host.replace(".csv", "") + ".p"

    tempDEC = Angle(transient_df['DEC'], unit=u.deg)
    tempDEC = tempDEC.deg

    df_North = transient_df[(tempDEC > -30)].reset_index()
    df_South = transient_df[(tempDEC <= -30)].reset_index()
    #print("Number of southern sources = %i.\n" % len(df_South))
    append=0
    if len(df_South) > 0:
        print("Finding southern sources with SkyMapper...")
        find_host_info_SH(df_South, fn_Host, dict_fn, path, rad)
        append=1
    #print("Number of northern sources = %i.\n" % len(df_North))
    if len(df_North) > 0:
        print("Finding northern sources with Pan-starrs...")
        find_host_info_PS1(df_North, fn_Host, dict_fn, path, rad, append=append)
    host_df = pd.read_csv(path+"/"+fn_Host)
    host_df = host_df.drop_duplicates()
    host_df.to_csv(path+"/"+fn_Host[:-4]+"_cleaned.csv", index=False)
    return host_df

def find_all(name, path):
    result = []
    for root, dirs, files in os.walk(path):
        if name in files:
            result.append(os.path.join(root, name))
    return result

def getimages(ra,dec,size=240,filters="grizy", type='stack'):

    """Query ps1filenames.py service to get a list of images

    ra, dec = position in degrees
    size = image size in pixels (0.25 arcsec/pixel)
    filters = string with filters to include
    Returns a table with the results
    """

    service = "https://ps1images.stsci.edu/cgi-bin/ps1filenames.py"
    url = ("{service}?ra={ra}&dec={dec}&size={size}&format=fits"
           "&filters={filters}&type={type}").format(**locals())
    table = Table.read(url, format='ascii')
    return table


def geturl(ra, dec, size=240, output_size=None, filters="grizy", format="jpg", color=False, type='stack'):

    """Get URL for images in the table

    ra, dec = position in degrees
    size = extracted image size in pixels (0.25 arcsec/pixel)
    output_size = output (display) image size in pixels (default = size).
                  output_size has no effect for fits format images.
    filters = string with filters to include
    format = data format (options are "jpg", "png" or "fits")
    color = if True, creates a color image (only for jpg or png format).
            Default is return a list of URLs for single-filter grayscale images.
    Returns a string with the URL
    """

    if color and format == "fits":
        raise ValueError("color images are available only for jpg or png formats")
    if format not in ("jpg","png","fits"):
        raise ValueError("format must be one of jpg, png, fits")
    table = getimages(ra,dec,size=size,filters=filters, type=type)
    url = ("https://ps1images.stsci.edu/cgi-bin/fitscut.cgi?"
           "ra={ra}&dec={dec}&size={size}&format={format}").format(**locals())
    if output_size:
        url = url + "&output_size={}".format(output_size)
    # sort filters from red to blue
    flist = ["yzirg".find(x) for x in table['filter']]
    table = table[np.argsort(flist)]
    if color:
        if len(table) > 3:
            # pick 3 filters
            table = table[[0,len(table)//2,len(table)-1]]
        for i, param in enumerate(["red","green","blue"]):
            url = url + "&{}={}".format(param,table['filename'][i])
    else:
        urlbase = url + "&red="
        url = []
        for filename in table['filename']:
            url.append(urlbase+filename)
    return url


def getcolorim(ra, dec, size=240, output_size=None, filters="grizy", format="jpg"):

    """Get color image at a sky position

    ra, dec = position in degrees
    size = extracted image size in pixels (0.25 arcsec/pixel)
    output_size = output (display) image size in pixels (default = size).
                  output_size has no effect for fits format images.
    filters = string with filters to include
    format = data format (options are "jpg", "png")
    Returns the image
    """

    if format not in ("jpg","png"):
        raise ValueError("format must be jpg or png")
    url = geturl(ra,dec,size=size,filters=filters,output_size=output_size,format=format,color=True, type='stack')
    r = requests.get(url)
    im = Image.open(BytesIO(r.content))
    return im


def getgrayim(ra, dec, size=240, output_size=None, filter="g", format="jpg"):

    """Get grayscale image at a sky position

    ra, dec = position in degrees
    size = extracted image size in pixels (0.25 arcsec/pixel)
    output_size = output (display) image size in pixels (default = size).
                  output_size has no effect for fits format images.
    filter = string with filter to extract (one of grizy)
    format = data format (options are "jpg", "png")
    Returns the image
    """

    if format not in ("jpg","png"):
        raise ValueError("format must be jpg or png")
    if filter not in list("grizy"):
        raise ValueError("filter must be one of grizy")
    url = geturl(ra,dec,size=size,filters=filter,output_size=output_size,format=format)
    r = requests.get(url[0])
    im = Image.open(BytesIO(r.content))
    return im

def get_PS1_type(ra, dec, rad, band, type):
    fitsurl = geturl(ra, dec, size=rad, filters="{}".format(band), format="fits", type=type)
    fh = fits.open(fitsurl[0])
    fh.writeto('PS1_ra={}_dec={}_{}arcsec_{}_{}.fits'.format(ra, dec, int(rad*0.25), band, type))

def get_PS1_wt(ra, dec, rad, band):
    fitsurl = geturl(ra, dec, size=rad, filters="{}".format(band), format="fits", type='stack.wt')
    fh = fits.open(fitsurl[0])
    fh.writeto('PS1_ra={}_dec={}_{}arcsec_{}_wt.fits'.format(ra, dec, int(rad*0.25), band))

def get_PS1_mask(ra, dec, rad, band):
    fitsurl = geturl(ra, dec, size=rad, filters="{}".format(band), format="fits", type='stack.mask')
    fh = fits.open(fitsurl[0])
    fh.writeto('PS1_ra={}_dec={}_{}arcsec_{}_mask.fits'.format(ra, dec, int(rad*0.25), band))

def get_PS1_Pic(objID, ra, dec, rad, band, safe=False):
    fitsurl = geturl(ra, dec, size=rad, filters="{}".format(band), format="fits")
    fh = fits.open(fitsurl[0])
    if safe==True:
        fh.writeto('PS1_{}_{}arcsec_{}.fits'.format(objID, int(rad*0.25), band))
    else:
        fh.writeto('PS1_ra={}_dec={}_{}arcsec_{}.fits'.format(ra, dec, int(rad*0.25), band))

# Data Lab
#from dl import queryClient as qc
#from dl.helpers.utils import convert

# set up Simple Image Access (SIA) service
DEF_ACCESS_URL = "http://datalab.noao.edu/sia/des_dr1"
svc = sia.SIAService(DEF_ACCESS_URL)

##################### PS1 HELPER FUNCTIONS ############################################
def ps1metadata(table="mean",release="dr1",baseurl="https://catalogs.mast.stsci.edu/api/v0.1/panstarrs"):
    """Return metadata for the specified catalog and table

    Parameters
    ----------
    table (string): mean, stack, or detection
    release (string): dr1 or dr2
    baseurl: base URL for the request

    Returns an astropy table with columns name, type, description
    """

    checklegal(table,release)
    url = "{baseurl}/{release}/{table}/metadata".format(**locals())
    r = requests.get(url)
    r.raise_for_status()
    v = r.json()
    # convert to astropy table
    tab = Table(rows=[(x['name'],x['type'],x['description']) for x in v],
               names=('name','type','description'))
    return tab


def mastQuery(request):
    """Perform a MAST query.

        Parameters
        ----------
        request (dictionary): The MAST request json object

        Returns head,content where head is the response HTTP headers, and content is the returned data"""

    server='mast.stsci.edu'

    # Grab Python Version
    version = ".".join(map(str, sys.version_info[:3]))

    # Create Http Header Variables
    headers = {"Content-type": "application/x-www-form-urlencoded",
               "Accept": "text/plain",
               "User-agent":"python-requests/"+version}

    # Encoding the request as a json string
    requestString = json.dumps(request)
    requestString = urlencode(requestString)

    # opening the https connection
    conn = httplib.HTTPSConnection(server)

    # Making the query
    conn.request("POST", "/api/v0/invoke", "request="+requestString, headers)

    # Getting the response
    resp = conn.getresponse()
    head = resp.getheaders()
    content = resp.read().decode('utf-8')

    # Close the https connection
    conn.close()

    return head,content

def resolve(name):
    """Get the RA and Dec for an object using the MAST name resolver

    Parameters
    ----------
    name (str): Name of object

    Returns RA, Dec tuple with position"""

    resolverRequest = {'service':'Mast.Name.Lookup',
                       'params':{'input':name,
                                 'format':'json'
                                },
                      }
    headers,resolvedObjectString = mastQuery(resolverRequest)
    resolvedObject = json.loads(resolvedObjectString)
    # The resolver returns a variety of information about the resolved object,
    # however for our purposes all we need are the RA and Dec
    try:
        objRa = resolvedObject['resolvedCoordinate'][0]['ra']
        objDec = resolvedObject['resolvedCoordinate'][0]['decl']
    except IndexError as e:
        raise ValueError("Unknown object '{}'".format(name))
    return (objRa, objDec)

def checklegal(table,release):
    """Checks if this combination of table and release is acceptable

    Raises a VelueError exception if there is problem
    """

    releaselist = ("dr1", "dr2")
    if release not in ("dr1","dr2"):
        raise ValueError("Bad value for release (must be one of {})".format(', '.join(releaselist)))
    if release=="dr1":
        tablelist = ("mean", "stack")
    else:
        tablelist = ("mean", "stack", "detection")
    if table not in tablelist:
        raise ValueError("Bad value for table (for {} must be one of {})".format(release, ", ".join(tablelist)))

def ps1search(table="mean",release="dr1",format="csv",columns=None,baseurl="https://catalogs.mast.stsci.edu/api/v0.1/panstarrs", verbose=False,**kw):
    """Do a general search of the PS1 catalog (possibly without ra/dec/radius)

    Parameters
    ----------
    table (string): mean, stack, or detection
    release (string): dr1 or dr2
    format: csv, votable, json
    columns: list of column names to include (None means use defaults)
    baseurl: base URL for the request
    verbose: print info about request
    **kw: other parameters (e.g., 'nDetections.min':2).  Note this is required!
    """

    data = kw.copy()
    if not data:
        raise ValueError("You must specify some parameters for search")
    checklegal(table,release)
    if format not in ("csv","votable","json"):
        raise ValueError("Bad value for format")
    url = "{baseurl}/{release}/{table}.{format}".format(**locals())
    if columns:
        # check that column values are legal
        # create a dictionary to speed this up
        dcols = {}
        for col in ps1metadata(table,release)['name']:
            dcols[col.lower()] = 1
        badcols = []
        for col in columns:
            if col.lower().strip() not in dcols:
                badcols.append(col)
        if badcols:
            raise ValueError('Some columns not found in table: {}'.format(', '.join(badcols)))
        # two different ways to specify a list of column values in the API
        # data['columns'] = columns
        data['columns'] = '[{}]'.format(','.join(columns))

# either get or post works
#    r = requests.post(url, data=data)
    r = requests.get(url, params=data)

    if verbose:
        print(r.url)
    r.raise_for_status()
    if format == "json":
        return r.json()
    else:
        return r.text


def ps1cone(ra,dec,radius,table="stack",release="dr1",format="csv",columns=None,baseurl="https://catalogs.mast.stsci.edu/api/v0.1/panstarrs", verbose=False,**kw):
    """Do a cone search of the PS1 catalog

    Parameters
    ----------
    ra (float): (degrees) J2000 Right Ascension
    dec (float): (degrees) J2000 Declination
    radius (float): (degrees) Search radius (<= 0.5 degrees)
    table (string): mean, stack, or detection
    release (string): dr1 or dr2
    format: csv, votable, json
    columns: list of column names to include (None means use defaults)
    baseurl: base URL for the request
    verbose: print info about request
    **kw: other parameters (e.g., 'nDetections.min':2)
    """

    data = kw.copy()
    data['ra'] = ra
    data['dec'] = dec
    data['radius'] = radius
    return ps1search(table=table,release=release,format=format,columns=columns,
                    baseurl=baseurl, verbose=verbose, **data)

#########################END PS1 HELPER FUNCTIONS##############################################

def create_df(tns_loc):
    """Combine all supernovae data into dataframe"""
    files = [f for f in listdir(tns_loc) if isfile(join(tns_loc, f))]
    arr = []
    for file in files:
        tempPD = pd.read_csv(tns_loc+file)
        arr.append(tempPD)
    df = pd.concat(arr)
    df = df.loc[df['RA'] != '00:00:00.000']
    df = df.drop_duplicates()
    df = df.replace({'Anon.': ''})
    df = df.replace({'2019-02-13.49': ''})
    df = df.apply(lambda x: x.str.strip() if x.dtype == "object" else x)
    return df
    #df.to_csv('SNe_TNS_061019.csv')

def query_ps1_noname(RA, DEC, rad):
    #print("Querying PS1 for nearest host...")
    return ps1cone(RA,DEC,rad/3600,table="stack",release="dr1",format="csv",columns=None,baseurl="https://catalogs.mast.stsci.edu/api/v0.1/panstarrs", verbose=False)

def query_ps1_name(name, rad):
    #print("Querying PS1 with host name!")
    [ra, dec] = resolve(name)
    return ps1cone(ra,dec,rad/3600,table="stack",release="dr1",format="csv",columns=None,baseurl="https://catalogs.mast.stsci.edu/api/v0.1/panstarrs", verbose=False)

# stolen from the wonderful API at https://ps1images.stsci.edu/ps1_dr2_api.html
def ps1metadata(table="mean",release="dr1",
           baseurl="https://catalogs.mast.stsci.edu/api/v0.1/panstarrs"):
    """Return metadata for the specified catalog and table

    Parameters
    ----------
    table (string): mean, stack, or detection
    release (string): dr1 or dr2
    baseurl: base URL for the request

    Returns an astropy table with columns name, type, description
    """

    checklegal(table,release)
    url = f"{baseurl}/{release}/{table}/metadata"
    r = requests.get(url)
    r.raise_for_status()
    v = r.json()
    # convert to astropy table
    tab = Table(rows=[(x['name'],x['type'],x['description']) for x in v],
               names=('name','type','description'))
    return tab

# Queries PS1 to find host info for each transient
# Input: df - a dataframe of all spectroscopically classified transients in TNS
#        fn - the output data frame of all PS1 potential hosts
#        dict_fn - the dictionary matching candidate hosts in PS1 and transients
# Output: N/A
def find_host_info_PS1(df, fn, dict_fn, path, rad, append=0):
    i = 0
    """Querying PS1 for all objects within rad arcsec of SNe"""
    #os.chdir()
    # SN_Host_PS1 - the dictionary to map SN IDs to nearby obj IDs in PS1
    # EDIT - We now know there are MANY SNe without IDs!! This is pretty problematic, so we're going to switch to
    # keeping a dictionary between names and objIDs
    SN_Host_PS1 = {}
    # PS1_queries - an array of relevant PS1 obj info
    PS1_queries = []
    for j, row in enumerate(df.itertuples(), 1):
            if ":" in str(row.RA):
                tempRA = Angle(row.RA, unit=u.hourangle)
            else:
                tempRA = Angle(row.RA, unit=u.deg)
            tempDEC = Angle(row.DEC, unit=u.deg)
            a = query_ps1_noname(tempRA.degree,tempDEC.degree, rad)
            if a:
                a = ascii.read(a)
                a = a.to_pandas()
                PS1_queries.append(a)
                SN_Host_PS1[row.Name] = np.array(a['objID'])
            else:
                SN_Host_PS1[row.Name] = np.array([])

            # Print status messages every 10 lines
            if j%10 == 0:
                print("Processed {} of {} lines!".format(j, len(df.Name)))
                #print(SN_Host_PS1)

            # Print every query to a file Note: this was done in order
            # to prevent the code crashing after processing 99% of the data
            # frame and losing everything. This allows for duplicates though,
            # so they should be removed before the file is used again
            if (len(PS1_queries) > 0):
                PS1_hosts = pd.concat(PS1_queries)
                PS1_hosts = PS1_hosts.drop_duplicates()
                newCols = np.array(['SkyMapper_StarClass', 'gelong','g_a','g_b','g_pa',
                'relong','r_a','r_b','r_pa',
                'ielong','i_a','i_b','i_pa',
                'zelong','z_a','z_b','z_pa'])
                for col in newCols:
                    PS1_hosts[col] = np.nan #match up rows to skymapper cols to join in one dataframe
                PS1_queries = []
                if not append:
                    PS1_hosts.to_csv(path+fn, header=True, index=False)
                    i = 1
                    append = True
                else:
                    PS1_hosts.to_csv(path+"/"+fn, mode='a+', header=False, index=False)
            else:
                print("No potential hosts found for this object...")
            # Save host info
            if not os.path.exists(path+ '/dictionaries/'):
            	os.makedirs(path+'/dictionaries/')
            option = "wb"
            if append:
                option = "ab"
            with open(path+"/dictionaries/" + dict_fn, option) as fp:
                pickle.dump(SN_Host_PS1, fp, protocol=pickle.HIGHEST_PROTOCOL)

def find_host_info_SH(df, fn, dict_fn, path, rad):
    i = 0
    """VO Cone Search for all objects within rad arcsec of SNe (for Southern-Hemisphere (SH) objects)"""
    SN_Host_SH = {}
    SH_queries = []
    pd.options.mode.chained_assignment = None
    for j, row in df.iterrows():
            if ":" in str(row.RA):
                tempRA = Angle(row.RA, unit=u.hourangle)
            else:
                tempRA = Angle(row.RA, unit=u.deg)
            tempDEC = Angle(row.DEC, unit=u.deg)
            a = pd.DataFrame({})
            a = southernSearch(tempRA.degree,tempDEC.degree, rad)
            if len(a)>0:
                SH_queries.append(a)
                SN_Host_SH[row.Name] = np.array(a['objID'])
            else:
                SN_Host_SH[row.Name] = np.array([])

            # Print status messages every 10 lines
            if j%10 == 0:
                print("Processed {} of {} lines!".format(j, len(df.Name)))
                #print(SN_Host_PS1)

            # Print every query to a file Note: this was done in order
            # to prevent the code crashing after processing 99% of the data
            # frame and losing everything. This allows for duplicates though,
            # so they should be removed before the file is used again
            if (len(SH_queries) > 0):
                SH_hosts = pd.concat(SH_queries)
                SH_hosts = SH_hosts.drop_duplicates()
                SH_queries = []
                if i == 0:
                    SH_hosts.to_csv(path+"/"+fn, header=True, index=False)
                    i = 1
                else:
                    SH_hosts.to_csv(path+"/"+fn, mode='a+', header=False, index=False)
            else:
                print("No potential hosts found for this object...")
            # Save host info
            if not os.path.exists(path+ '/dictionaries/'):
            	os.makedirs(path+'/dictionaries/')
            with open(path+"/dictionaries/" + dict_fn, 'wb') as fp:
                pickle.dump(SN_Host_SH, fp, protocol=pickle.HIGHEST_PROTOCOL)
    pd.options.mode.chained_assignment = 'warn'

def southernSearch(ra, dec, rad):
    searchCoord = SkyCoord(ra*u.deg, dec*u.deg, frame='icrs')
    responseMain = requests.get("http://skymapper.anu.edu.au/sm-cone/public/query?CATALOG=dr2.master&RA=%.5f&DEC=%.5f&SR=%.5f&RESPONSEFORMAT=CSV&VERB=3" %(ra, dec, (rad/3600)))
    responsePhot = requests.get("http://skymapper.anu.edu.au/sm-cone/public/query?CATALOG=dr2.photometry&RA=%.5f&DEC=%.5f&SR=%.5f&RESPONSEFORMAT=CSV&VERB=3" %(ra, dec, (rad/3600)))

    dfMain = pd.read_csv(BytesIO(responseMain.content))
    dfPhot = pd.read_csv(BytesIO(responsePhot.content))

    filt_dfs = []
    for filter in 'griz':
        #add the photometry columns
        tempDF = dfPhot[dfPhot['filter']==filter]
        if len(tempDF) <1:
            tempDF.append(pd.Series(), ignore_index=True) #add dummy row for the sake of not crashing
        for col in tempDF.columns.values:
            if col != 'object_id':
                tempDF[filter + col] = tempDF[col]
                del tempDF[col]
        #take the column with the smallest uncertainty in the measured semi-major axis - this is what we'll use to
        #calculate DLR later!
        tempDF = tempDF.loc[tempDF.groupby("object_id")[filter + 'e_a'].idxmin()]
        filt_dfs.append(tempDF)

    test = filt_dfs[0]

    for i in np.arange(1, len(filt_dfs)):
        test = test.merge(filt_dfs[i], on='object_id', how='outer')

    test['object_id'] =  np.nan_to_num(test['object_id'])
    test['object_id'] = test['object_id'].astype(np.int64)

    fullDF = test.merge(dfMain, on='object_id', how='outer')

    flag_mapping = {'objID':'object_id', 'raMean':'raj2000',
        'decMean':'dej2000','gKronRad':'gradius_kron',
        'rKronRad':'rradius_kron', 'iKronRad':'iradius_kron',
        'zKronRad':'iradius_kron', 'yKronRad':np.nan,
        'gPSFMag':'g_psf', 'rPSFMag':'r_psf','iPSFMag':'i_psf',
        'zPSFMag':'z_psf','yPSFMag':np.nan,'gPSFMagErr':'e_g_psf',
        'rPSFMagErr':'e_r_psf','iPSFMagErr':'e_i_psf','zPSFMagErr':'e_z_psf',
        'yPSFMagErr':np.nan,'gKronMag':'g_petro', 'rKronMag':'r_petro',
        'iKronMag':'i_petro', 'zKronMag':'z_petro', 'yKronMag':np.nan,
        'gKronMagErr':'e_g_petro', 'rKronMagErr':'e_r_petro',
        'iKronMagErr':'e_i_petro', 'zKronMagErr':'e_z_petro',
        'yKronMagErr':np.nan, 'ng':'g_ngood', 'nr':'r_ngood', 'ni':'i_ngood',
        'nz':'z_ngood', 'graErr':'e_raj2000', 'rraErr':'e_raj2000', 'iraErr':'e_raj2000',
        'zraErr':'e_raj2000', 'gdecErr':'e_dej2000', 'rdecErr':'e_dej2000','idecErr':'e_dej2000',
        'zdecErr':'e_dej2000','l':'glon', 'b':'glat', 'gra':'gra_img', 'rra':'rra_img', 'ira':'ira_img',
        'zra':'zra_img', 'yra':'raj2000', 'gdec':'gdecl_img', 'rdec':'rdecl_img',
        'idec':'idecl_img', 'zdec':'zdecl_img', 'ydec':'dej2000', 'gKronFlux':'gflux_kron',
        'rKronFlux':'rflux_kron', 'iKronFlux':'iflux_kron', 'zKronFlux':'zflux_kron', 'yKronFlux':np.nan,
        'gKronFluxErr':'ge_flux_kron', 'rKronFluxErr':'re_flux_kron', 'iKronFluxErr':'ie_flux_kron',
        'zKronFluxErr':'ze_flux_kron', 'yKronFluxErr':np.nan,
        'gPSFFlux':'gflux_psf',
        'rPSFFlux':'rflux_psf', 'iKronFlux':'iflux_psf', 'zKronFlux':'zflux_psf', 'yKronFlux':np.nan,
        'gPSFFluxErr':'ge_flux_psf', 'rKronFluxErr':'re_flux_psf', 'iKronFluxErr':'ie_flux_psf',
        'zPSFFluxErr':'ze_flux_psf', 'yKronFluxErr':np.nan, 'gpsfChiSq':'gchi2_psf',
        'rpsfChiSq':'rchi2_psf', 'ipsfChiSq':'ichi2_psf', 'zpsfChiSq':'zchi2_psf',
        'ypsfChiSq':np.nan, 'nDetections':'ngood', 'SkyMapper_StarClass':'rclass_star',
        'distance':'r_cntr', 'objName':'object_id',
        'g_elong':'gelong', 'g_a':'ga', 'g_b':'gb', 'g_pa':'gpa',
        'r_elong':'relong', 'r_a':'ra', 'r_b':'rb', 'r_pa':'rpa',
        'i_elong':'ielong', 'i_a':'ia', 'i_b':'ib', 'i_pa':'ipa',
        'z_elong':'zelong', 'z_a':'za', 'z_b':'zb', 'z_pa':'zpa'} #'class_star' should be added

    keepCols = []
    for band in 'griz':
        for rad in ['radius_petro', 'radius_frac20', 'radius_frac50', 'radius_frac90']:
            flag_mapping[band + rad] = band + rad
            keepCols.append(band + rad)

    df_cols = np.array(list(flag_mapping.values()))
    mapped_cols = np.array(list(flag_mapping.keys()))

    PS1_cols = np.array(['objName', 'objAltName1', 'objAltName2', 'objAltName3', 'objID',
           'uniquePspsOBid', 'ippObjID', 'surveyID', 'htmID', 'zoneID',
           'tessID', 'projectionID', 'skyCellID', 'randomID', 'batchID',
           'dvoRegionID', 'processingVersion', 'objInfoFlag', 'qualityFlag',
           'raStack', 'decStack', 'raStackErr', 'decStackErr', 'raMean',
           'decMean', 'raMeanErr', 'decMeanErr', 'epochMean', 'posMeanChisq',
           'cx', 'cy', 'cz', 'lambda', 'beta', 'l', 'b', 'nStackObjectRows',
           'nStackDetections', 'nDetections', 'ng', 'nr', 'ni', 'nz', 'ny',
           'uniquePspsSTid', 'primaryDetection', 'bestDetection',
           'gippDetectID', 'gstackDetectID', 'gstackImageID', 'gra', 'gdec',
           'graErr', 'gdecErr', 'gEpoch', 'gPSFMag', 'gPSFMagErr', 'gApMag',
           'gApMagErr', 'gKronMag', 'gKronMagErr', 'ginfoFlag', 'ginfoFlag2',
           'ginfoFlag3', 'gnFrames', 'gxPos', 'gyPos', 'gxPosErr', 'gyPosErr',
           'gpsfMajorFWHM', 'gpsfMinorFWHM', 'gpsfTheta', 'gpsfCore',
           'gpsfLikelihood', 'gpsfQf', 'gpsfQfPerfect', 'gpsfChiSq',
           'gmomentXX', 'gmomentXY', 'gmomentYY', 'gmomentR1', 'gmomentRH',
           'gPSFFlux', 'gPSFFluxErr', 'gApFlux', 'gApFluxErr', 'gApFillFac',
           'gApRadius', 'gKronFlux', 'gKronFluxErr', 'gKronRad', 'gexpTime',
           'gExtNSigma', 'gsky', 'gskyErr', 'gzp', 'gPlateScale',
           'rippDetectID', 'rstackDetectID', 'rstackImageID', 'rra', 'rdec',
           'rraErr', 'rdecErr', 'rEpoch', 'rPSFMag', 'rPSFMagErr', 'rApMag',
           'rApMagErr', 'rKronMag', 'rKronMagErr', 'rinfoFlag', 'rinfoFlag2',
           'rinfoFlag3', 'rnFrames', 'rxPos', 'ryPos', 'rxPosErr', 'ryPosErr',
           'rpsfMajorFWHM', 'rpsfMinorFWHM', 'rpsfTheta', 'rpsfCore',
           'rpsfLikelihood', 'rpsfQf', 'rpsfQfPerfect', 'rpsfChiSq',
           'rmomentXX', 'rmomentXY', 'rmomentYY', 'rmomentR1', 'rmomentRH',
           'rPSFFlux', 'rPSFFluxErr', 'rApFlux', 'rApFluxErr', 'rApFillFac',
           'rApRadius', 'rKronFlux', 'rKronFluxErr', 'rKronRad', 'rexpTime',
           'rExtNSigma', 'rsky', 'rskyErr', 'rzp', 'rPlateScale',
           'iippDetectID', 'istackDetectID', 'istackImageID', 'ira', 'idec',
           'iraErr', 'idecErr', 'iEpoch', 'iPSFMag', 'iPSFMagErr', 'iApMag',
           'iApMagErr', 'iKronMag', 'iKronMagErr', 'iinfoFlag', 'iinfoFlag2',
           'iinfoFlag3', 'inFrames', 'ixPos', 'iyPos', 'ixPosErr', 'iyPosErr',
           'ipsfMajorFWHM', 'ipsfMinorFWHM', 'ipsfTheta', 'ipsfCore',
           'ipsfLikelihood', 'ipsfQf', 'ipsfQfPerfect', 'ipsfChiSq',
           'imomentXX', 'imomentXY', 'imomentYY', 'imomentR1', 'imomentRH',
           'iPSFFlux', 'iPSFFluxErr', 'iApFlux', 'iApFluxErr', 'iApFillFac',
           'iApRadius', 'iKronFlux', 'iKronFluxErr', 'iKronRad', 'iexpTime',
           'iExtNSigma', 'isky', 'iskyErr', 'izp', 'iPlateScale',
           'zippDetectID', 'zstackDetectID', 'zstackImageID', 'zra', 'zdec',
           'zraErr', 'zdecErr', 'zEpoch', 'zPSFMag', 'zPSFMagErr', 'zApMag',
           'zApMagErr', 'zKronMag', 'zKronMagErr', 'zinfoFlag', 'zinfoFlag2',
           'zinfoFlag3', 'znFrames', 'zxPos', 'zyPos', 'zxPosErr', 'zyPosErr',
           'zpsfMajorFWHM', 'zpsfMinorFWHM', 'zpsfTheta', 'zpsfCore',
           'zpsfLikelihood', 'zpsfQf', 'zpsfQfPerfect', 'zpsfChiSq',
           'zmomentXX', 'zmomentXY', 'zmomentYY', 'zmomentR1', 'zmomentRH',
           'zPSFFlux', 'zPSFFluxErr', 'zApFlux', 'zApFluxErr', 'zApFillFac',
           'zApRadius', 'zKronFlux', 'zKronFluxErr', 'zKronRad', 'zexpTime',
           'zExtNSigma', 'zsky', 'zskyErr', 'zzp', 'zPlateScale',
           'yippDetectID', 'ystackDetectID', 'ystackImageID', 'yra', 'ydec',
           'yraErr', 'ydecErr', 'yEpoch', 'yPSFMag', 'yPSFMagErr', 'yApMag',
           'yApMagErr', 'yKronMag', 'yKronMagErr', 'yinfoFlag', 'yinfoFlag2',
           'yinfoFlag3', 'ynFrames', 'yxPos', 'yyPos', 'yxPosErr', 'yyPosErr',
           'ypsfMajorFWHM', 'ypsfMinorFWHM', 'ypsfTheta', 'ypsfCore',
           'ypsfLikelihood', 'ypsfQf', 'ypsfQfPerfect', 'ypsfChiSq',
           'ymomentXX', 'ymomentXY', 'ymomentYY', 'ymomentR1', 'ymomentRH',
           'yPSFFlux', 'yPSFFluxErr', 'yApFlux', 'yApFluxErr', 'yApFillFac',
           'yApRadius', 'yKronFlux', 'yKronFluxErr', 'yKronRad', 'yexpTime',
           'yExtNSigma', 'ysky', 'yskyErr', 'yzp', 'yPlateScale', 'distance', 'SkyMapper_StarClass',
           'g_elong','g_a','g_b','g_pa',
           'r_elong','r_a','r_b','r_pa',
           'i_elong','i_a','i_b','i_pa',
           'z_elong','z_a','z_b','z_pa'])

    for i in np.arange(len(df_cols)):
        if df_cols[i] == 'nan':
            fullDF[mapped_cols[i]] = np.nan
        else:
            fullDF[mapped_cols[i]] = fullDF[df_cols[i]]

    fullDF['gPlateScale'] = 0.50 #''/px
    fullDF['rPlateScale'] = 0.50 #''/px
    fullDF['iPlateScale'] = 0.50 #''/px
    fullDF['zPlateScale'] = 0.50 #''/px #plate scale of skymapper
    fullDF['yPlateScale'] = 0.50
    fullDF['primaryDetection'] = 1
    fullDF['bestDetection'] = 1
    fullDF['qualityFlag'] = 0 #dummy variable set so that no sources get cut by qualityFlag in PS1 (which isn't in SkyMapper)
    fullDF['ny'] = 1 #dummy variable
    colSet = np.concatenate([list(flag_mapping.keys()), ['gPlateScale', 'rPlateScale',
        'iPlateScale', 'zPlateScale', 'yPlateScale', 'primaryDetection', 'bestDetection', 'qualityFlag', 'ny']])

    fullDF = fullDF[colSet]

    leftover = set(PS1_cols) - set(fullDF.columns.values)
    for col in leftover:
        fullDF[col] = np.nan

    #fullDF = fullDF[PS1_cols] #arrange correctly
    fullDF.drop_duplicates(subset=['objID'], inplace=True)
    return fullDF

def getDR2_petrosianSizes(ra_arr, dec_arr, rad):
    if len(ra_arr) < 1:
        return
    
    halfLightList = []
    for i in np.arange(len(ra_arr)):
        query = """select st.objID, st.primaryDetection, st.gpetR90, st.rpetR90, st.ipetR90, st.zpetR90, st.ypetR90
        from fGetNearbyObjEq(%.3f,%.3f,%.1f/60.0) nb
        inner join StackPetrosian st on st.objID=nb.objid where st.primaryDetection = 1""" %(ra_arr[i], dec_arr[i], rad)

        jobs = mastcasjobs.MastCasJobs(context="PanSTARRS_DR2")
        tab = jobs.quick(query, task_name="halfLightSearch")
        df_halfLight = tab.to_pandas()
        halfLightList.append(df_halfLight)

    df_halfLight_full = pd.concat(halfLightList)
    return df_halfLight_full

def getDR2_halfLightSizes(ra_arr, dec_arr, rad):
    if len(ra_arr) < 1:
        return

    halfLightList = []
    for i in np.arange(len(ra_arr)):
        query = """select st.objID, st.primaryDetection, st.gHalfLightRad, st.rHalfLightRad, st.iHalfLightRad,
        st.zHalfLightRad, st.yHalfLightRad from fGetNearbyObjEq(%.3f,%.3f,%.1f/60.0) nb
        inner join StackModelFitExtra st on st.objID=nb.objid where st.primaryDetection = 1""" %(ra_arr[i], dec_arr[i], rad)

        jobs = mastcasjobs.MastCasJobs(context="PanSTARRS_DR2")
        tab = jobs.quick(query, task_name="halfLightSearch")
        df_halfLight = tab.to_pandas()
        halfLightList.append(df_halfLight)

    df_halfLight_full = pd.concat(halfLightList)
    return df_halfLight_full
