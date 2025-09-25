import re, os

from dirmap import MappedFSTree, FileMap
from dirmap.opus_fs import extmap as to_lossy_extmap, namemap as to_lossy_namemap

def main() :
    original_audio_root = os.environ["ORIGINAL_AUDIO_ROOT"]
    playlist_target_root = os.environ["PLAYLIST_TARGET_ROOT"]
    lossy_playlists_root = os.environ["LOSSY_PLAYLIST_ROOT"]

    android_audio_root_pattern = os.environ["ANDROID_AUDIO_ROOT_PATTERN"] # "FF7F-A5BA/media/audio"

    to_lossy_filemap = FileMap(extension_map = to_lossy_extmap)
    to_lossy_fstree = MappedFSTree(original_audio_root, file_map = to_lossy_filemap, name_map = to_lossy_namemap)

    def extmap(ext: str) :
        if ext != "m3u8" :
            return ext
        return "m3u"
        
    def ftransform(path) :
        with open(path, "r") as f:
            text = f.read()

            FPATH_GROUPIDX=1
            matches_b2f = list(re.finditer(android_audio_root_pattern + r"([^\n]+)", text))
            matches_b2f.reverse()
            # iterate matches back to front so we don't have to adjust
            # string-indices.
            for match in matches_b2f :
                targetfile = match.group(FPATH_GROUPIDX)

                real_fpath = to_lossy_fstree.real_direntry(targetfile).path
                text = text[0:match.start()] + real_fpath + text[match.end():]
            
            return text.encode("utf-8")

    def datamap(path) :
        if path[-4:] == "m3u8" :
            return ftransform(path)
        else :
            return open(path, "rb")

    def sizemap(de: os.DirEntry) :
        # mpd needs accurate sizes.

        # return de.stat(follow_symlinks=True).st_size * 2
        return len(ftransform(de.path))

    filemap = FileMap(data_map = datamap, size_map = sizemap, extension_map = extmap)

    fstree = MappedFSTree(lossy_playlists_root, file_map = filemap)
    fstree.init_fuse(playlist_target_root)
