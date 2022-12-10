
import collections
import sys

import numpy as np

class HDFDataset:
    def __init__(self):
        self.id = ""
        self.attributes = collections.OrderedDict()
        self.columns = collections.OrderedDict()
        self.data = None

    def copy(self, ds):
        self.copyAttributes(ds)
        self.data = np.copy(ds.data)

    def copyAttributes(self, ds):
        for k,v in ds.attributes.items():
            self.attributes[k] = v

    def colDeleteRow(self, i):
        for k in self.columns:
            col = self.columns[k]
            # Reverse the order of index to avoid changing index conflict
            j = sorted(i, reverse=True)
            for index in j:
                del col[0][index]

    def printd(self):
        print("Dataset:", self.id)

    def read(self, f):
        name = f.name[f.name.rfind("/")+1:]
        self.id = name

        # Read attributes
        for k in f.attrs.keys():
            if type(f.attrs[k]) == np.ndarray:
                #print(f.attrs[k])
                #print(type(f.attrs[k].tolist()[0]))
                if type(f.attrs[k].tolist()[0]) == bytes:
                    self.attributes[k] = [k.decode("utf-8") for k in f.attrs[k]]
                    #print("Attr:", self.attributes[k])
                else:
                    self.attributes[k] = [k for k in f.attrs[k]]

            else:
                if type(f.attrs[k]) == bytes:
                    self.attributes[k] = f.attrs[k].decode("utf-8")
                else:
                    self.attributes[k] = f.attrs[k]
        #print(f)
        #print(type(f[:]))

        # Read dataset
        self.data = f[:] # Gets converted to numpy.ndarray
        #print("Dataset:", name)
        #print("Data:", self.data.dtype)

    def write(self, f):
        #print("id:", self.id)
        #print("columns:", self.columns)
        #print("data:", self.data)

        if self.data is not None:
            dset = f.create_dataset(self.id, data=self.data, dtype=self.data.dtype)
        else:
            print("Dataset.write(): Data is None")

    def getColumn(self, name):
        if name in self.columns:
            return self.columns[name]
        return None

    def appendColumn(self, name, val):
        if name not in self.columns:
            self.columns[name] = [val]
        else:
            self.columns[name].append(val)

    def datasetToColumns(self):
        ''' Converts numpy array into columns (stored as a dictionary) '''
        if self.data is None:
            print("Warning - datasetToColumns: data is empty")
            return
        self.columns = collections.OrderedDict()
        for k in self.data.dtype.names:
            #print("type",type(ltData.data[k]))
            self.columns[k] = self.data[k].tolist()

    def datasetToColumns2(self):
        ''' Convert Prosoft format numpy array to columns '''
        if self.data is None:
            print("Warning - datasetToColumns2: data is empty")
            return
        self.columns = collections.OrderedDict()
        ids = self.attributes["ID"]
        for k in ids:
            self.columns[k] = []
        for k in ids:
            self.columns[k].append(self.data[0][ids.index(k)])

    def columnsToDataset(self):
        ''' Converts columns into numpy array '''
        #dtype0 = np.dtype([(name, type(ds.columns[name][0])) for name in ds.columns.keys()])

        if not self.columns:
            print("Warning - columnsToDataset: raw data column is empty")
            print("Id:", self.id) #, ", Columns:", self.columns)
            return False

        dtype = []
        for name in self.columns.keys():

            # Numpy dtype column name cannot be unicode in Python 2
            if sys.version_info[0] < 3:
                name = name.encode('utf-8')

            if self.id == "MESSAGE": # For SATMSG strings, buffer the data type for stings longer than the first one
                maxlength = 0
                for item in self.columns[name]:
                    length = len(item)
                    if length > maxlength:
                        maxlength = length

                dtype.append((name, "|S" + str(maxlength))) # immutable tuple(())
            else:

                item = self.columns[name][0]
                if isinstance(item, bytes):
                    #dtype.append((name, h5py.special_dtype(vlen=str)))
                    dtype.append((name, "|S" + str(len(item))))
                    #dtype.append((name, np.dtype(str)))
                # Note: hdf4 only supports 32 bit int, convert to float64
                elif isinstance(item, int):
                    dtype.append((name, np.float64))
                elif name.endswith('FLAG'):
                    dtype.append((name, np.int))
                else:
                    dtype.append((name, type(item)))

        shape = (len(list(self.columns.values())[0]), )
        #print("Id:", self.id)
        #print("Dtype:", dtype)
        #print("Shape:", shape)
        self.data = np.empty(shape, dtype=dtype) # empty means uninitialized, i.e. random values.
        for k,v in self.columns.items():
            # HDF5 deliberately makes including string vectors difficult
            # These will all be changed to floats or ints in HDFDataset.columnsToDataset
            if k.endswith('FLAG'):
                # Interpret as undeclared, field, model, or default: 0, 1, 2, 3
                if v[0] == 'undetermined':
                    v = 0
                elif v[0] == 'field':
                    v = 1
                elif v[0] == 'model':
                    v = 2
                elif v[0] == 'default':
                    v = 3

            self.data[k] = v

        return True

    def changeColName(self,oldName,newName):
        ''' Change the name of a column and push to dataset '''
        self.datasetToColumns()
        for name in self.columns.copy():
            if name == oldName:
                # self.appendColumn(newName, self.columns[oldName])
                self.columns[newName] = self.columns[oldName]
                del self.columns[oldName]
        self.columnsToDataset()
