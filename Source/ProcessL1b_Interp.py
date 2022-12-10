
import collections
import datetime as dt
import calendar
from inspect import currentframe, getframeinfo

import numpy as np
import scipy as sp

import HDFRoot
from Utilities import Utilities
from ConfigFile import ConfigFile


class ProcessL1b_Interp:

    @staticmethod
    def interpolateL1b_Interp(xData, xTimer, yTimer, newXData, dataName, kind='linear', fileName='default'):
        ''' Time interpolation
            xTimer, yTimer are already converted from TimeTag2 to Datetimes'''

        # List of datasets requiring angular interpolation (i.e. through 0 degrees)
        angList = ['AZIMUTH', 'POINTING', 'REL_AZ', 'HEADING', 'SOLAR_AZ', 'SZA']

        # List of datasets requiring fill instead of interpolation
        fillList = ['STATION']

        for k in xData.data.dtype.names:
            if k == "Datetag" or k == "Timetag2" or k == "Datetime":
                continue
            # print(k)
            x = list(xTimer)
            new_x = list(yTimer)
            y = np.copy(xData.data[k]).tolist()

            # Because x is now a list of datetime tuples, they'll need to be
            # converted to Unix timestamp values
            xTS = [calendar.timegm(xDT.utctimetuple()) + xDT.microsecond / 1E6 for xDT in x]
            newXTS = [calendar.timegm(xDT.utctimetuple()) + xDT.microsecond / 1E6 for xDT in new_x]

            if dataName in angList:
                ''' BUG: Unlike interp, interpAngular defaults to fill by extrapolation rather than
                filling with the last actual value. This is probably only advisable for SOLAR_AZ.'''
                if dataName == 'SOLAR_AZ' or dataName == 'SZA':
                    newXData.columns[k] = Utilities.interpAngular(xTS, y, newXTS, fill_value="extrapolate")
                else:
                    newXData.columns[k] = Utilities.interpAngular(xTS, y, newXTS, fill_value=0)
                # Some angular measurements (like SAS pointing) are + and -, and get converted
                # to all +. Convert them back to - for 180-359
                if dataName == "POINTING":
                    pointingData = newXData.columns[k]
                    for i, angle in enumerate(pointingData):
                        if angle > 180:
                            pointingData[i] = angle - 360

            elif dataName in fillList:
                newXData.columns[k] = Utilities.interpFill(xTS,y,newXTS, fillValue=np.nan)

            else:
                if kind == 'cubic':
                    newXData.columns[k] = Utilities.interpSpline(xTS, y, newXTS)
                else:
                    newXData.columns[k] = Utilities.interp(xTS,y,newXTS, fill_value=np.nan)

        if ConfigFile.settings["bL1bPlotTimeInterp"] == 1 and dataName != 'T':
            print('Plotting time interpolations ' +dataName)
            # Plots the interpolated data in /Plots/
            ''' TO DO: This is still broken on Mac. See the hack to fix it here: https://github.com/pandas-dev/pandas/issues/22859'''
            Utilities.plotTimeInterp(xData, xTimer, newXData, yTimer, dataName, fileName)

    @staticmethod
    def convertDataset(group, datasetName, newGroup, newDatasetName):
        ''' Converts a sensor group into the L1E format; option to change dataset name.
            Moves dataset to new group.
            The separate DATETAG, TIMETAG2, and DATETIME datasets are combined into
            the sensor dataset. This also adds a temporary column in the sensor data
            array for datetime to be used in interpolation. This is later removed, as
            HDF5 does not support datetime. '''

        dataset = group.getDataset(datasetName)
        dateData = group.getDataset("DATETAG")
        timeData = group.getDataset("TIMETAG2")
        dateTimeData = group.getDataset("DATETIME")

        # Convert degrees minutes to decimal degrees format; only for GPS, not ANCILLARY_METADATA
        if group.id.startswith("GP"):
            if newDatasetName == "LATITUDE":
                latPosData = group.getDataset("LATPOS")
                latHemiData = group.getDataset("LATHEMI")
                for i in range(dataset.data.shape[0]):
                    latDM = latPosData.data["NONE"][i]
                    latDirection = latHemiData.data["NONE"][i]
                    latDD = Utilities.dmToDd(latDM, latDirection)
                    latPosData.data["NONE"][i] = latDD
            if newDatasetName == "LONGITUDE":
                lonPosData = group.getDataset("LONPOS")
                lonHemiData = group.getDataset("LONHEMI")
                for i in range(dataset.data.shape[0]):
                    lonDM = lonPosData.data["NONE"][i]
                    lonDirection = lonHemiData.data["NONE"][i]
                    lonDD = Utilities.dmToDd(lonDM, lonDirection)
                    lonPosData.data["NONE"][i] = lonDD

        newSensorData = newGroup.addDataset(newDatasetName)

        # Datetag, Timetag2, and Datetime columns added to sensor data array
        newSensorData.columns["Datetag"] = dateData.data["NONE"].tolist()
        newSensorData.columns["Timetag2"] = timeData.data["NONE"].tolist()
        newSensorData.columns["Datetime"] = dateTimeData.data

        # Copies over the sensor dataset from original group to newGroup
        for k in dataset.data.dtype.names: # For each waveband (or vector data for other groups)
            #print("type",type(esData.data[k]))
            newSensorData.columns[k] = dataset.data[k].tolist()
        newSensorData.columnsToDataset()

    @staticmethod
    def interpolateData(xData, yData, dataName, fileName):
        ''' Preforms time interpolation to match xData to yData. xData is the dataset to be
        interpolated, yData is the reference dataset with the times to be interpolated to.'''

        msg = f'Interpolate Data {dataName}'
        print(msg)
        Utilities.writeLogFile(msg)

        # Interpolating to itself
        if xData is yData:
            msg = 'Skip. Other instruments are being interpolated to this one.'
            print(msg)
            Utilities.writeLogFile(msg)
            return True

        xDatetime = xData.data["Datetime"].tolist()
        yDatetime = yData.data["Datetime"].tolist()
        print('Interpolating '+str(len(xDatetime))+' timestamps from '+\
            str(min(xDatetime))+' to '+str(max(xDatetime)))
        print('           To '+str(len(yDatetime))+' timestamps from '+\
            str(min(yDatetime))+' to '+str(max(yDatetime)))

        # xData will be interpolated to yDatetimes
        xData.columns["Datetag"] = yData.data["Datetag"].tolist()
        xData.columns["Timetag2"] = yData.data["Timetag2"].tolist()
        xData.columns["Datetime"] = yData.data["Datetime"].tolist()

        if Utilities.hasNan(xData):
            frameinfo = getframeinfo(currentframe())
            # print(frameinfo.filename, frameinfo.lineno)
            msg = f'found NaN {frameinfo.lineno}'
            print(msg)
            Utilities.writeLogFile(msg)

        # Perform interpolation on full hyperspectral time series
        ProcessL1b_Interp.interpolateL1b_Interp(xData, xDatetime, yDatetime, xData, dataName, 'linear', fileName)

        xData.columnsToDataset()

        if Utilities.hasNan(xData):
            frameinfo = getframeinfo(currentframe())
            msg = f'found NaN {frameinfo.lineno}'
            print(msg)
            Utilities.writeLogFile(msg)
        return True

    @staticmethod
    def interpolateWavelength(ds, newDS, newWavebands):
        ''' Wavelength Interpolation
            Use a common waveband set determined by the maximum lowest wavelength
            of all sensors, the minimum highest wavelength, and the interval
            set in the Configuration Window. '''

        # Copy dataset to dictionary
        ds.datasetToColumns()
        columns = ds.columns
        saveDatetag = columns.pop("Datetag")
        saveTimetag2 = columns.pop("Timetag2")
        columns.pop("Datetime")

        # Get wavelength values
        wavelength = []
        for k in columns:
            wavelength.append(float(k))

        x = np.asarray(wavelength)

        newColumns = collections.OrderedDict()
        newColumns["Datetag"] = saveDatetag
        newColumns["Timetag2"] = saveTimetag2
        # Can leave Datetime off at this point

        for i in range(newWavebands.shape[0]):
            # limit to one decimal place
            newColumns[str(round(10*newWavebands[i])/10)] = []

        # Perform interpolation for each timestamp
        for timeIndex in range(len(saveDatetag)):
            values = []

            for k in columns:
                values.append(columns[k][timeIndex])

            y = np.asarray(values)
            #new_y = sp.interpolate.interp1d(x, y)(newWavebands)
            new_y = sp.interpolate.InterpolatedUnivariateSpline(x, y, k=3)(newWavebands)

            for waveIndex in range(newWavebands.shape[0]):
                newColumns[str(round(10*newWavebands[waveIndex])/10)].append(new_y[waveIndex])

        newDS.columns = newColumns
        newDS.columnsToDataset()


    # @staticmethod
    # def getDataAverage(n, data, time, width):
    #     ''' Determines points to average data
    #         Note: Prosoft always includes 1 point left/right of n
    #         even if it is outside of specified width.

    #         Not implemented in v1.0.B'''

    #     lst = [data[n]]
    #     i = n-1
    #     while i >= 0:
    #         lst.append(data[i])
    #         if (time[n] - time[i]) > width:
    #             break
    #         i -= 1
    #     i = n+1
    #     while i < len(time):
    #         lst.append(data[i])
    #         if (time[i] - time[n]) > width:
    #             break
    #         i += 1
    #     avg = 0
    #     for v in lst:
    #         avg += v
    #     avg /= len(lst)
    #     return avg

    # @staticmethod
    # def matchColumns(esData, liData, ltData):
    #     ''' Makes each dataset have matching wavelength values

    #         Not required; only for testing '''

    #     msg = "Match Columns"
    #     print(msg)
    #     Utilities.writeLogFile(msg)

    #     esData.datasetToColumns()
    #     liData.datasetToColumns()
    #     ltData.datasetToColumns()

    #     matchMin = -1
    #     matchMax = -1

    #     # Determine the minimum and maximum values for k
    #     for ds in [esData, liData, ltData]:
    #         nMin = -1
    #         nMax = -1
    #         for k in ds.columns.keys():
    #             if Utilities.isFloat(k):
    #                 num = float(k)
    #                 if nMin == -1:
    #                     nMin = num
    #                     nMax = num
    #                 elif num < nMin:
    #                     nMin = num
    #                 elif num > nMax:
    #                     nMax = num
    #         if matchMin == -1:
    #             matchMin = nMin
    #             matchMax = nMax
    #         if matchMin < nMin:
    #             matchMin = nMin
    #         if matchMax > nMax:
    #             matchMax = nMax

    #     # Remove values to match minimum and maximum
    #     for ds in [esData, liData, ltData]:
    #         l = []
    #         for k in ds.columns.keys():
    #             if Utilities.isFloat(k):
    #                 num = float(k)
    #                 if num < matchMin:
    #                     l.append(k)
    #                 elif num > matchMax:
    #                     l.append(k)
    #         for k in l:
    #             del ds.columns[k]

    #     esData.columnsToDataset()
    #     liData.columnsToDataset()
    #     ltData.columnsToDataset()

    @staticmethod
    def matchWavelengths(node):
        ''' Wavelength matching through interpolation.
            PySciDON interpolated each instrument to a different set of bands.
            Here we use a common set determined by the maximum lowest wavelength
            of all sensors, the minimum highest wavelength, and the interval
            set in the Configuration Window. '''

        print('Interpolating to common wavelengths')
        root = HDFRoot.HDFRoot()
        root.copyAttributes(node)

        interval = float(ConfigFile.settings["fL1bInterpInterval"])

        newReferenceGroup = root.addGroup("IRRADIANCE")
        newSASGroup = root.addGroup("RADIANCE")
        root.groups.append(node.getGroup("GPS"))
        if node.getGroup("ANCILLARY_METADATA"):
            root.groups.append(node.getGroup("ANCILLARY_METADATA"))
        if node.getGroup("SOLARTRACKER"):
            root.groups.append(node.getGroup("SOLARTRACKER"))
        if node.getGroup("SOLARTRACKER_STATUS"):
            root.groups.append(node.getGroup("SOLARTRACKER_STATUS"))
        if node.getGroup("PYROMETER"):
            root.groups.append(node.getGroup("PYROMETER"))

        referenceGroup = node.getGroup("IRRADIANCE")
        sasGroup = node.getGroup("RADIANCE")

        esData = referenceGroup.getDataset("ES")
        liData = sasGroup.getDataset("LI")
        ltData = sasGroup.getDataset("LT")

        newESData = newReferenceGroup.addDataset("ES")
        newLIData = newSASGroup.addDataset("LI")
        newLTData = newSASGroup.addDataset("LT")

        # Es dataset to dictionary
        esData.datasetToColumns()
        columns = esData.columns
        columns.pop("Datetag")
        columns.pop("Timetag2")
        columns.pop("Datetime")
        # Get wavelength values
        esWavelength = []
        for k in columns:
            esWavelength.append(float(k))
        # Determine interpolated wavelength values
        esStart = np.ceil(esWavelength[0])
        esEnd = np.floor(esWavelength[len(esWavelength)-1])

        # Li dataset to dictionary
        liData.datasetToColumns()
        columns = liData.columns
        columns.pop("Datetag")
        columns.pop("Timetag2")
        columns.pop("Datetime")
        # Get wavelength values
        liWavelength = []
        for k in columns:
            liWavelength.append(float(k))
        # Determine interpolated wavelength values
        liStart = np.ceil(liWavelength[0])
        liEnd = np.floor(liWavelength[len(liWavelength)-1])

        # Lt dataset to dictionary
        ltData.datasetToColumns()
        columns = ltData.columns
        columns.pop("Datetag")
        columns.pop("Timetag2")
        columns.pop("Datetime")
        # Get wavelength values
        ltWavelength = []
        for k in columns:
            ltWavelength.append(float(k))

        # Determine interpolated wavelength values
        ltStart = np.ceil(ltWavelength[0])
        ltEnd = np.floor(ltWavelength[len(liWavelength)-1])

        # No extrapolation
        start = max(esStart,liStart,ltStart)
        end = min(esEnd,liEnd,ltEnd)
        newWavebands = np.arange(start, end, interval)

        print('Interpolating Es')
        ProcessL1b_Interp.interpolateWavelength(esData, newESData, newWavebands)
        print('Interpolating Li')
        ProcessL1b_Interp.interpolateWavelength(liData, newLIData, newWavebands)
        print('Interpolating Lt')
        ProcessL1b_Interp.interpolateWavelength(ltData, newLTData, newWavebands)

        return root

    @staticmethod
    def processL1b_Interp(node, fileName):
        '''
        Process time and wavelength interpolation across instruments and ancillary data
        '''
        # Add a dataset to each group for DATETIME, as defined by TIMETAG2 and DATETAG
        # node  = Utilities.rootAddDateTime(node)

        root = HDFRoot.HDFRoot() # creates a new instance of HDFRoot Class
        root.copyAttributes(node) # Now copy the attributes in from the L1a object
        now = dt.datetime.now()
        timestr = now.strftime("%d-%b-%Y %H:%M:%S")
        # root.attributes["FILE_CREATION_TIME"] = timestr
        # if  ConfigFile.settings["bL1bDefaultCal"]:
        #     root.attributes['CAL_TYPE'] = 'Default/Factory'
        # else:
        #     root.attributes['CAL_TYPE'] = 'Full Character'
        root.attributes['WAVE_INTERP'] = str(ConfigFile.settings['fL1bInterpInterval']) + ' nm'

        msg = f"ProcessL1b_Interp.processL1b_Interp: {timestr}"
        print(msg)
        Utilities.writeLogFile(msg)

        gpsGroup = None
        pyrGroup = None
        esGroup = None
        liGroup = None
        ltGroup = None
        satnavGroup = None
        ancGroup = None # For non-SolarTracker deployments
        satmsgGroup = None
        for gp in node.groups:
            if gp.id.startswith("GP"):
                gpsGroup = gp
            if gp.id.startswith("PYROMETER"):
                pyrGroup = gp
            if gp.id.startswith("ES"):
                esGroup = gp
            if gp.id.startswith("LI"):
                liGroup = gp
            if gp.id.startswith("LT"):
                ltGroup = gp
            if gp.id == "SOLARTRACKER" or gp.id =="SOLARTRACKER_pySAS":
                satnavGroup = gp # Now labelled SOLARTRACKER at L1B to L1D
            if gp.id == ("ANCILLARY_METADATA"):
                ancGroup = gp
            if gp.id == "SOLARTRACKER_STATUS":
                satmsgGroup = gp

        # New group scheme combines both radiance sensors in one group
        refGroup = root.addGroup("IRRADIANCE")
        sasGroup = root.addGroup("RADIANCE")

        # Conversion of datasets within groups to move date/timestamps into
        # the data arrays and add datetime column. Also can change dataset name.
        # Places the dataset into the new group.
        ProcessL1b_Interp.convertDataset(esGroup, "ES", refGroup, "ES")
        ProcessL1b_Interp.convertDataset(liGroup, "LI", sasGroup, "LI")
        ProcessL1b_Interp.convertDataset(ltGroup, "LT", sasGroup, "LT")

        newGPSGroup = root.addGroup("GPS")
        if gpsGroup is not None:
            # These are from the raw data, not to be confused with those in the ancillary file
            ProcessL1b_Interp.convertDataset(gpsGroup, "LATPOS", newGPSGroup, "LATITUDE")
            ProcessL1b_Interp.convertDataset(gpsGroup, "LONPOS", newGPSGroup, "LONGITUDE")
            latData = newGPSGroup.getDataset("LATITUDE")
            lonData = newGPSGroup.getDataset("LONGITUDE")
            # Only if the right NMEA data are provided (e.g. with SolarTracker)
            if gpsGroup.attributes["CalFileName"].startswith("GPRMC"):
                ProcessL1b_Interp.convertDataset(gpsGroup, "COURSE", newGPSGroup, "COURSE")
                ProcessL1b_Interp.convertDataset(gpsGroup, "SPEED", newGPSGroup, "SPEED")
                courseData = newGPSGroup.getDataset("COURSE")
                sogData = newGPSGroup.getDataset("SPEED")
                newGPSGroup.datasets['SPEED'].id="SOG"
        else:
            # These are from the ancillary file
            ProcessL1b_Interp.convertDataset(ancGroup, "LATITUDE", newGPSGroup, "LATITUDE")
            ProcessL1b_Interp.convertDataset(ancGroup, "LONGITUDE", newGPSGroup, "LONGITUDE")
            latData = newGPSGroup.getDataset("LATITUDE")
            lonData = newGPSGroup.getDataset("LONGITUDE")

        # Metadata ancillary field and Pysolar data
        if ancGroup is not None:
            newAncGroup = root.addGroup("ANCILLARY_METADATA")
            newAncGroup.attributes = ancGroup.attributes.copy()
            for ds in ancGroup.datasets:
                if ds != "DATETAG" and ds != "TIMETAG2" and ds != "DATETIME":
                    ProcessL1b_Interp.convertDataset(ancGroup, ds, newAncGroup, ds)

            if satnavGroup is None:
                # Required:
                relAzData = newAncGroup.getDataset("REL_AZ")
                szaData = newAncGroup.getDataset("SZA")
                solAzData = newAncGroup.getDataset("SOLAR_AZ")
            # Optional:
            stationData = None
            headingDataAnc = None
            latDataAnc = None
            lonDataAnc = None
            cloudData = None
            waveData = None
            speedData = None
            # Optional and may reside in SolarTracker or SATTHS group
            pitchData = None
            rollData = None
            # Optional, assured with MERRA2 models when selected
            saltData = None
            sstData = None
            windData = None
            aodData = None
            # Optional:
            if "STATION" in newAncGroup.datasets:
                stationData = newAncGroup.getDataset("STATION")
            if "HEADING" in newAncGroup.datasets:
                headingDataAnc = newAncGroup.getDataset("HEADING") # This HEADING derives from ancillary data file (NOT GPS or pySAS)
            if "LATITUDE" in newAncGroup.datasets:
                latDataAnc = newAncGroup.getDataset("LATITUDE")
            if "LONGITUDE" in newAncGroup.datasets:
                lonDataAnc = newAncGroup.getDataset("LONGITUDE")
            if "SALINITY" in newAncGroup.datasets:
                saltData = newAncGroup.getDataset("SALINITY")
            if "SST" in newAncGroup.datasets:
                sstData = newAncGroup.getDataset("SST")
            if "WINDSPEED" in newAncGroup.datasets:
                windData = newAncGroup.getDataset("WINDSPEED")
            if "AOD" in newAncGroup.datasets:
                aodData = newAncGroup.getDataset("AOD")
            if "CLOUD" in newAncGroup.datasets:
                cloudData = newAncGroup.getDataset("CLOUD")
            if "WAVE_HT" in newAncGroup.datasets:
                waveData = newAncGroup.getDataset("WAVE_HT")
            if "SPEED_F_W" in newAncGroup.datasets:
                speedData = newAncGroup.getDataset("SPEED_F_W")
            # Allow for the unlikely option that pitch/roll data are included in both the SolarTracker/pySAS and Ancillary datasets
            if "PITCH" in newAncGroup.datasets:
                pitchAncData = newAncGroup.getDataset("PITCH")
            if "ROLL" in newAncGroup.datasets:
                rollAncData = newAncGroup.getDataset("ROLL")

        if satnavGroup is not None:
            newSTGroup = root.addGroup("SOLARTRACKER")
            # Required
            # ProcessL1b_Interp.convertDataset(satnavGroup, "AZIMUTH", newSTGroup, "AZIMUTH")
            # ProcessL1b_Interp.convertDataset(satnavGroup, "ELEVATION", newSTGroup, "ELEVATION")
            ProcessL1b_Interp.convertDataset(satnavGroup, "SOLAR_AZ", newSTGroup, "SOLAR_AZ")
            solAzData = newSTGroup.getDataset("SOLAR_AZ")
            ProcessL1b_Interp.convertDataset(satnavGroup, "SZA", newSTGroup, "SZA")
            szaData = newSTGroup.getDataset("SZA")
            ProcessL1b_Interp.convertDataset(satnavGroup, "REL_AZ", newSTGroup, "REL_AZ")
            relAzData = newSTGroup.getDataset("REL_AZ")
            ProcessL1b_Interp.convertDataset(satnavGroup, "POINTING", newSTGroup, "POINTING")
            pointingData = newSTGroup.getDataset("POINTING")

            # Optional
            # ProcessL1b_Interp.convertDataset(satnavGroup, "HEADING", newSTGroup, "HEADING") # Use SATNAV Heading if available (not GPS COURSE)
            if "HUMIDITY" in satnavGroup.datasets:
                ProcessL1b_Interp.convertDataset(satnavGroup, "HUMIDITY", newSTGroup, "HUMIDITY")
                humidityData = newSTGroup.getDataset("HUMIDITY")
            if "PITCH" in satnavGroup.datasets:
                ProcessL1b_Interp.convertDataset(satnavGroup, "PITCH", newSTGroup, "PITCH")
                pitchData = newSTGroup.getDataset("PITCH")
            if "ROLL" in satnavGroup.datasets:
                ProcessL1b_Interp.convertDataset(satnavGroup, "ROLL", newSTGroup, "ROLL")
                rollData = newSTGroup.getDataset("ROLL")
            headingData = None
            if "HEADING" in satnavGroup.datasets:
                ProcessL1b_Interp.convertDataset(satnavGroup, "HEADING", newSTGroup, "HEADING")
                headingData = newSTGroup.getDataset("HEADING")

        if satmsgGroup is not None:
            newSatMSGGroup = root.addGroup("SOLARTRACKER_STATUS")
            # SATMSG (SOLARTRACKER_STATUS) has no date or time, just propogate it as is
            satMSG = satmsgGroup.getDataset("MESSAGE")
            newSatMSG = newSatMSGGroup.addDataset("MESSAGE")
            # newSatMSGGroup["MESSAGE"] = satMSG
            # Copies over the dataset
            for k in satMSG.data.dtype.names:
                #print("type",type(esData.data[k]))
                newSatMSG.columns[k] = satMSG.data[k].tolist()
            newSatMSG.columnsToDataset()

        if pyrGroup is not None:
            newPyrGroup = root.addGroup("PYROMETER")
            ProcessL1b_Interp.convertDataset(pyrGroup, "T", newPyrGroup, "T")
            pyrData = newPyrGroup.getDataset("T")

        # PysciDON interpolated to the SLOWEST sampling rate and ProSoft
        # interpolates to the FASTEST. Not much in the literature on this, although
        # Brewin et al. RSE 2016 used the slowest instrument on the AMT cruises,
        # which makes the most sense for minimizing error.
        esData = refGroup.getDataset("ES") # array with columns date, time, esdata*wavebands...
        liData = sasGroup.getDataset("LI")
        ltData = sasGroup.getDataset("LT")

        # Interpolate all datasets to the SLOWEST radiometric sampling rate
        esLength = len(esData.data["Timetag2"].tolist())
        liLength = len(liData.data["Timetag2"].tolist())
        ltLength = len(ltData.data["Timetag2"].tolist())

        interpData = None
        if esLength < liLength and esLength < ltLength:
            msg = f"ES has fewest records - interpolating to ES. This should raise a red flag; {esLength} records"
            print(msg)
            Utilities.writeLogFile(msg)
            interpData = esData
        elif liLength < ltLength:
            msg = f"LI has fewest records - interpolating to LI. This should raise a red flag; {liLength} records"
            print(msg)
            Utilities.writeLogFile(msg)
            interpData = liData
        else:
            msg = f"LT has fewest records (as expected) - interpolating to LT; {ltLength} records"
            print(msg)
            Utilities.writeLogFile(msg)
            interpData = ltData

        # Perform time interpolation

        # Note that only the specified datasets in each group will be interpolated and
        # carried forward. For radiometers, this means that ancillary metadata such as
        # SPEC_TEMP and THERMAL_RESP will be dropped at L1E and beyond.
        # Required:
        if not ProcessL1b_Interp.interpolateData(esData, interpData, "ES", fileName):
            return None
        if not ProcessL1b_Interp.interpolateData(liData, interpData, "LI", fileName):
            return None
        if not ProcessL1b_Interp.interpolateData(ltData, interpData, "LT", fileName):
            return None
        if not ProcessL1b_Interp.interpolateData(latData, interpData, "LATITUDE", fileName):
            return None
        if not ProcessL1b_Interp.interpolateData(lonData, interpData, "LONGITUDE", fileName):
            return None
        if gpsGroup is not None:
            if gpsGroup.attributes["CalFileName"].startswith("GPRMC"):
                # Optional:
                ProcessL1b_Interp.interpolateData(courseData, interpData, "COURSE", fileName) # COG (not heading), presumably?
                ProcessL1b_Interp.interpolateData(sogData, interpData, "SOG", fileName)

        if satnavGroup is not None:
            # Required:
            if not ProcessL1b_Interp.interpolateData(relAzData, interpData, "REL_AZ", fileName):
                return None
            if not ProcessL1b_Interp.interpolateData(szaData, interpData, "SZA", fileName):
                return None
            # Optional, but should all be there with the SOLAR TRACKER or pySAS
            ProcessL1b_Interp.interpolateData(solAzData, interpData, "SOLAR_AZ", fileName)
            ProcessL1b_Interp.interpolateData(pointingData, interpData, "POINTING", fileName)

            # Optional
            if "HUMIDITY" in satnavGroup.datasets:
                ProcessL1b_Interp.interpolateData(humidityData, interpData, "HUMIDITY", fileName)
            if "PITCH" in satnavGroup.datasets:
                ProcessL1b_Interp.interpolateData(pitchData, interpData, "PITCH", fileName)
            if "ROLL" in satnavGroup.datasets:
                ProcessL1b_Interp.interpolateData(rollData, interpData, "ROLL", fileName)
            if "HEADING" in satnavGroup.datasets:
                ProcessL1b_Interp.interpolateData(headingData, interpData, "HEADING", fileName)

        if ancGroup is not None:
            if satnavGroup is None:
                # Required:
                if not ProcessL1b_Interp.interpolateData(relAzData, interpData, "REL_AZ", fileName):
                    return None
                if not ProcessL1b_Interp.interpolateData(szaData, interpData, "SZA", fileName):
                    return None
                if not ProcessL1b_Interp.interpolateData(solAzData, interpData, "SOLAR_AZ", fileName):
                    return None
            else:
                if relAzData:
                    ProcessL1b_Interp.interpolateData(relAzData, interpData, "REL_AZ", fileName)
                if szaData:
                    ProcessL1b_Interp.interpolateData(szaData, interpData, "SZA", fileName)
                if solAzData:
                    ProcessL1b_Interp.interpolateData(solAzData, interpData, "SOLAR_AZ", fileName)

            # Optional:
            if stationData:
                ProcessL1b_Interp.interpolateData(stationData, interpData, "STATION", fileName)
            if aodData:
                ProcessL1b_Interp.interpolateData(aodData, interpData, "AOD", fileName)
            if headingDataAnc:
                ProcessL1b_Interp.interpolateData(headingDataAnc, interpData, "HEADING", fileName)
            if latDataAnc:
                ConfigFile.settings["bL1b_InterpPlotTimeInterp"] = 0 # Reserve lat/lon plots for actual GPS, not ancillary file
                ProcessL1b_Interp.interpolateData(latDataAnc, interpData, "LATITUDE", fileName)
                ConfigFile.settings["bL1b_InterpPlotTimeInterp"] = 1
            if lonDataAnc:
                ConfigFile.settings["bL1b_InterpPlotTimeInterp"] = 0
                ProcessL1b_Interp.interpolateData(lonDataAnc, interpData, "LONGITUDE", fileName)
                ConfigFile.settings["bL1b_InterpPlotTimeInterp"] = 1
            if saltData:
                ProcessL1b_Interp.interpolateData(saltData, interpData, "SALINITY", fileName)
            if sstData:
                ProcessL1b_Interp.interpolateData(sstData, interpData, "SST", fileName)
            if windData:
                ProcessL1b_Interp.interpolateData(windData, interpData, "WINDSPEED", fileName)
            if cloudData:
                ProcessL1b_Interp.interpolateData(cloudData, interpData, "CLOUD", fileName)
            if waveData:
                ProcessL1b_Interp.interpolateData(waveData, interpData, "WAVE_HT", fileName)
            if speedData:
                ProcessL1b_Interp.interpolateData(speedData, interpData, "SPEED_F_W", fileName)
            if "PITCH" in ancGroup.datasets:
                ProcessL1b_Interp.interpolateData(pitchAncData, interpData, "PITCH", fileName)
            if "ROLL" in ancGroup.datasets:
                ProcessL1b_Interp.interpolateData(rollAncData, interpData, "ROLL", fileName)

        if pyrGroup is not None:
            # Optional:
            ProcessL1b_Interp.interpolateData(pyrData, interpData, "T", fileName)

        # Match wavelengths across instruments
        # Calls interpolateWavelengths and matchColumns
        # Includes columnsToDataset for only the radiometry, for remaining groups, see below
        root = ProcessL1b_Interp.matchWavelengths(root)

        #ProcessL1b_Interp.dataAveraging(newESData)
        #ProcessL1b_Interp.dataAveraging(newLIData)
        #ProcessL1b_Interp.dataAveraging(newLTData)

        # DATETIME is not supported in HDF5; remove from groups that still have it
        for gp in root.groups:
            for dsName in gp.datasets:
                ds = gp.datasets[dsName]
                if "Datetime" in ds.columns:
                    ds.columns.pop("Datetime")
                ds.columnsToDataset() # redundant for radiometry, but harmless

        return root
