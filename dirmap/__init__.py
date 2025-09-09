import os, stat, errno, math, io
import fuse
from fuse import Fuse, FuseArgs
fuse.fuse_python_api = (0, 2)
from collections.abc import Callable
from pprint import pp
from copy import deepcopy
from enum import Enum

import logging
logger = logging.getLogger(__name__)

# map file-extensions.
ExtensionMap = Callable[[str], str]
def default_extensionmap(extension: str) :
    return extension

SizeMap = Callable[[os.DirEntry], int]
def default_sizemap(de: os.DirEntry) :
    return de.stat(follow_symlinks=True).st_size

class MappedFileType(Enum):
    BYTES=1
    PIPE=2
    FILE=3

# map file-data.
# TextIOWrapper is file-backed stream (seekable), BufferedReader is
# pipe-output.
DataMap = Callable[[str], bytes|io.TextIOWrapper|io.BufferedReader]
def default_datamap(path: str) :
    with open(path, "rb") as f :
        data = f.read()
        return data

# map file-paths/direntries.
NameMap = Callable[[str], str]
def default_namemap(direntry: str) :
    return direntry

class FileMap :
    # data_map receives a path to a real file and returns `bytes`.
    # extension_map returns the file-extension of the mapped file (so we can know the complete filename).
    def __init__(self,
                 extension_map: ExtensionMap = default_extensionmap,
                 data_map: DataMap = default_datamap,
                 size_map: SizeMap = default_sizemap) :
        self.extension_map = extension_map
        self.data_map = data_map
        self.size_map = size_map

default_filemap = FileMap()

def map_fname(name: str, name_map: NameMap, ext_map: ExtensionMap) :
    last_dot_idx = name.rfind(".")
    if last_dot_idx == 0 :
        # keep hidden files hidden.
        return "." + name_map(name[last_dot_idx+1:])
    else :
        fname = name[:last_dot_idx]
        ext = name[last_dot_idx+1:]
        mapped_name = name_map(fname) + "." + ext_map(ext)
        # print(f"name is {name}, parsed as {fname}:{ext}, mapped to {mapped_name}")
        return mapped_name

def map_dirname(name: str, name_map: NameMap) :
    last_dot_idx = name.rfind(".")
    if last_dot_idx == 0 :
        # keep hidden directories hidden.
        return "." + name_map(name[last_dot_idx+1:])
    else :
        return name_map(name)

# represents a directory.
class MappedDir :
    def __init__(self, real_path: str, name_map: NameMap, file_map: FileMap) :
        assert(real_path != None)
        assert(name_map != None)
        assert(file_map != None)

        self.real_path = real_path
        self.name_map = name_map
        self.file_map = file_map


    def childnames(self) :
        res = []
        for de in os.scandir(path=self.real_path) :
            if de.is_dir(follow_symlinks=True) :
                res.append(map_dirname(de.name, name_map = self.name_map))
            else :
                res.append(map_fname(de.name, name_map = self.name_map, ext_map = self.file_map.extension_map))
        return res

    def child_dir(self, realpath) :
        return MappedDir(real_path = realpath, name_map = self.name_map, file_map =self.file_map)

    def relative_real_direntry(self, path_components) :
        for de in os.scandir(path=self.real_path) :
            mapped_name = None
            if de.is_dir(follow_symlinks=True) :
                mapped_name = map_dirname(de.name, name_map = self.name_map)
            else :
                mapped_name = map_fname(de.name, name_map = self.name_map, ext_map = self.file_map.extension_map)
            if mapped_name == path_components[0] :
                if len(path_components) == 1 :
                    return de
                else :
                    if not de.is_dir(follow_symlinks=True) :
                        raise Exception("Tried indexing file as directory!")
                    # remove one component.
                    return self.child_dir(de.path).relative_real_direntry(path_components[1:])
        raise Exception("Could not find requested path!")

def split_path(path) :
    return [i for i in path.split("/") if i != ""]

class MyStat(fuse.Stat):
    def __init__(self):
        self.st_mode = 0
        self.st_ino = 0
        self.st_dev = 0
        self.st_nlink = 0
        self.st_uid = 0
        self.st_gid = 0
        self.st_size = 0
        self.st_atime = 0
        self.st_mtime = 0
        self.st_ctime = 0

class MappedFSTree :
    def __init__(self, root: str, name_map: NameMap = default_namemap, file_map: FileMap = default_filemap) :
        self.root = root
        self.name_map = name_map
        self.file_map = file_map

        self.root_dir = MappedDir(
            real_path = root,
            name_map = name_map,
            file_map = file_map)

    def real_direntry(self, path) :
        path_components = split_path(path)
        return self.root_dir.relative_real_direntry(path_components)
        
    def stat(self, path) :
        st = MyStat()

        real_de = self.real_direntry(path)
        real_stat = real_de.stat()

        if real_de.is_dir(follow_symlinks=True) :
            st.st_mode = stat.S_IFDIR | 0o555
            st.st_nlink = 2
        else :
            st.st_mode = stat.S_IFREG | 0o444
            st.st_nlink = 1
            st.st_size = self.file_map.size_map(real_de)

        st.st_atime = math.floor(real_stat.st_atime)
        st.st_mtime = math.floor(real_stat.st_mtime)
        st.st_ctime = math.floor(real_stat.st_ctime)

        return st

    def childnames(self, path) :
        if path == "/" :
            md = self.root_dir
        else :
            de = self.real_direntry(path)
            md = MappedDir(de.path, name_map = self.name_map, file_map = self.file_map)
        return md.childnames()

    def init_fuse(self, mountpoint) :
        fa = FuseArgs()
        fa.mountpoint = mountpoint
        server = FuseImpl(
                    self,
                    version="%prog " + fuse.__version__,
                    dash_s_do='setsingle',
                    fuse_args=fa)

        server.parse(errex=1)
        server.main()


class FuseImpl(Fuse):
    def __init__(self, fs_map: MappedFSTree, *args, **kw) :
        Fuse.__init__(self, *args, **kw)
        self._fs_map = fs_map

    def getattr(self, path):
        if path == "/" :
            return os.lstat(self._fs_map.root)

        try :
            return self._fs_map.stat(path)
        except Exception as e:
            logger.critical(e, exc_info=True)
            return -errno.ENOENT

    def readdir(self, path, offset):
        try :
            childnames = self._fs_map.childnames(path)
        except Exception as e:
            logger.critical(e, exc_info=True)
            return -errno.ENOENT

        childnames.insert(1, ".")
        childnames.insert(1, "..")

        for c in childnames :
            yield fuse.Direntry(c)
    
    class FuseFile :
        # set from outside.
        mapped_fstree: MappedFSTree

        def __init__(self, path, flags, *mode):
            accmode = os.O_RDONLY | os.O_WRONLY | os.O_RDWR
            if (flags & accmode) != os.O_RDONLY:
                return -errno.EACCES

            mapped_path = self.mapped_fstree.real_direntry(path).path
            mapped = self.mapped_fstree.file_map.data_map(mapped_path)
            if isinstance(mapped, bytes) :
                self.data = mapped
                self.mode = MappedFileType.BYTES
            elif isinstance(mapped, io.TextIOWrapper) :
                self.f = mapped
                self.mode = MappedFileType.FILE
            elif isinstance(mapped, io.BufferedReader) :
                self.stdout = mapped
                self.data = bytearray()
                # MiB*10
                self.blksize = 1024*1024*1
                self.read_done = False
                self.mode = MappedFileType.PIPE
            else :
                logger.critical(f"Cannot handle type returned from `data_map`: {type(mapped)}", exc_info=True)
                return -errno.EACCES

        def read(self, size, offset) :
            match self.mode:
                case MappedFileType.BYTES :
                    slen = len(self.data)
                    if offset < slen:
                        if offset + size > slen:
                            size = slen - offset
                        buf = self.data[offset:offset+size]
                    else:
                        buf = b''
                    return buf
                case MappedFileType.FILE :
                    self.f.seek(offset)
                    #print(f"seeked to {offset}")
                    return self.f.read(size)
                case MappedFileType.PIPE :
                    # once pipe is exhausted, just return data.
                    if self.read_done :
                        return self.data[offset:offset+size]

                    while len(self.data) < offset+size :
                        b = self.stdout.read(self.blksize)
                        if b == b"" :
                            self.read_done = True
                            break
                        # print(f"read {len(b)} bytes from stream!")
                        self.data.extend(b)
                    return self.data[offset:offset+size]

        def release(self, flags) :
            if self.mode == MappedFileType.FILE :
                self.f.close()
            elif self.mode == MappedFileType.PIPE :
                self.stdout.close()

    def new_file(self, path, flags, *mode) :
        return self.FuseFile(self._fs_map.file_map, path, flags, *mode)

    def main(self, *a, **kw) :
        file_class = deepcopy(self.FuseFile)
        file_class.mapped_fstree = self._fs_map

        self.file_class = file_class
        return Fuse.main(self, *a, **kw)
