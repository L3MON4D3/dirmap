from dirmap import MappedFSTree, FileMap, map_fname
import subprocess, os, re, sys
from slugify import slugify

def extmap(ext: str) :
    if ext != "flac" :
        return ext
    return "opus"

def namemap(name: str) :
    # leave 6 characters for the extension, should suffice :)
    # (max of 256 chars on some old filesystems.)
    slug = slugify(
        name,
        replacements=[
            ['Ü', 'UE'],
            ['ü', 'ue'],
            ['Ä', 'AE'],
            ['ä', 'ae'],
            ['Ö', 'OE'],
            ['ö', 'oe'],
        ],
        max_length=250)
    return slug if slug != "" else "-"

def datamap(path) :
    if path[-4:] == "flac" :
        proc = subprocess.Popen(
            ["ffmpeg", "-i", path, "-b:a", "128k", "-map_metadata", "0", "-f", "opus", "pipe:1"],
            stdin=None, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return proc.stdout
    elif path[-3:] == "cue" :
        with open(path, "r") as f:
            text = f.read()
            FNAME_GROUPIDX=1
            matches_b2f = list(re.finditer(r"FILE\s+\"([^\"]+)\"", text))
            matches_b2f.reverse()
            # iterate matches back to front so we don't have to adjust
            # string-indices.
            for match in matches_b2f :
                targetfile = match.group(FNAME_GROUPIDX)
                # out map-fname can't handle path-separators.
                assert(targetfile.find("/") == -1)

                mapped_fname = map_fname(targetfile, name_map = namemap, ext_map = extmap)
                text = text[0:match.start(FNAME_GROUPIDX)] + mapped_fname + text[match.end(FNAME_GROUPIDX):]
            
            return text.encode("utf-8")
    else :
        return open(path, "rb")

def sizemap(de: os.DirEntry) :
    # overestimate filesize. opus will have much lower filesize than flac, and
    # the cuesheet modification will probably add like 10 bytes.
    return de.stat(follow_symlinks=True).st_size + 1000

def main() :
    filemap = FileMap(extension_map = extmap, data_map = datamap, size_map = sizemap)

    fstree = MappedFSTree(sys.argv[1], file_map = filemap, name_map = namemap)
    fstree.init_fuse(sys.argv[2])
