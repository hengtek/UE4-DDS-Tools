import os
from io_util import *
from uasset import Uasset
from umipmap import Umipmap

#classes for texture assets (.uexp and .ubulk)

BYTE_PER_PIXEL = {
    'DXT1/BC1': 0.5,
    'DXT5/BC3': 1,
    'BC4/ATI1': 0.5,
    'BC4(signed)': 0.5,
    'BC5/ATI2': 1,
    'BC5(signed)': 1, 
    'BC6H(unsigned)': 1,
    'BC6H(signed)': 1,
    'BC7': 1,
    'FloatRGBA': 8,
    'B8G8R8A8(sRGB)': 4
}

PF_FORMAT = {
    'PF_DXT1': 'DXT1/BC1',
    'PF_DXT5': 'DXT5/BC3',
    'PF_BC4': 'BC4/ATI1',
    'PF_BC5': 'BC5/ATI2',
    'PF_BC6H': 'BC6H(unsigned)',
    'PF_BC7': 'BC7', 
    'PF_FloatRGBA': 'FloatRGBA',
    'PF_B8G8R8A8': 'B8G8R8A8(sRGB)'
}

def is_power_of_2(n):
    if n==1:
        return True
    if n%2!=0:
        return False
    return is_power_of_2(n//2)

#get all file paths for texture asset from a file path.
EXT = ['.uasset', '.uexp', '.ubulk']
def get_all_file_path(file):
    base_name, ext = os.path.splitext(file)
    if ext not in EXT:
        raise RuntimeError('Not Uasset. ({})'.format(file))
    return [base_name + ext for ext in EXT]

#texture class for ue4
class Utexture:
    UNREAL_SIGNATURE = b'\xC1\x83\x2A\x9E'
    UBULK_FLAG = [0, 16384]
    
    def __init__(self, file_path, version='ff7r', verbose=False):
        self.version = version
        
        if not os.path.isfile(file_path):
            raise RuntimeError('Not File. ({})'.format(file_path))

        uasset_name, uexp_name, ubulk_name = get_all_file_path(file_path)
        print('load: ' + uasset_name)

        #read .uasset
        self.uasset = Uasset(uasset_name)
        if len(self.uasset.exports)!=1:
            raise RuntimeError('Unexpected number of exports')

        self.uasset_size = self.uasset.size
        self.name_list = self.uasset.name_list
        self.texture_type = self.uasset.texture_type
        
        #read .uexp
        with open(uexp_name, 'rb') as f:
            self.read_uexp(f)
            if self.version=='4.27':
                read_null(f)
            check(self.end_offset, f.tell()+self.uasset_size)
            self.none_name_id = read_uint64(f)
            
            foot=f.read()

            check(foot, Utexture.UNREAL_SIGNATURE)

        #read .ubulk
        if self.has_ubulk:
            with open(ubulk_name, 'rb') as f:
                size = get_size(f)
                for mip in self.mipmaps:
                    if mip.uexp:
                        continue
                    mip.data = f.read(mip.data_size)
                check(size, f.tell())

        self.print(verbose)
    
    #read uexp
    def read_uexp(self, f):
        #read cooked size if exist
        if self.version=='ff7r':
            f.read(1)
            b = f.read(1)
            while (b not in [b'\x03', b'\x05']):
                f.read(1)
                b = f.read(1)
            s = f.tell()
            f.seek(0)
            self.bin1=f.read(s)
            self.original_width = read_uint32(f)
            self.original_height = read_uint32(f)
        else:
            first_property_id = read_uint32(f)
            if first_property_id>=len(self.name_list):
                raise RuntimeError('list index out of range. Make sure UE4 version is correct in ./src/config.json.')
            first_property = self.name_list[first_property_id]
            f.seek(0)
            if first_property=='ImportedSize':
                self.bin1 = f.read(49)
                self.original_width = read_uint32(f)
                self.original_height = read_uint32(f)
            else:
                self.bin1 = None

        #skip property part        
        offset=f.tell()
        b = f.read(8)
        while (b!=b'\x01\x00\x01\x00\x01\x00\x00\x00'):
            b=b''.join([b[1:], f.read(1)])
        s=f.tell()-offset
        f.seek(offset)        
        self.unk = f.read(s)

        #read meta data
        self.type_name_id = read_uint64(f)
        self.offset_to_end_offset = f.tell()
        self.end_offset = read_uint32(f) #Offset to end of uexp?
        if self.version in ['4.27', 'bloodstained']:
            read_null(f)
        f.seek(8, 1) #original width and height
        self.cube_flag = read_uint16(f)
        self.unk_int = read_uint16(f)
        if self.cube_flag==1:
            if self.texture_type!='2D':
                raise RuntimeError('Unexpected error')
        elif self.cube_flag==6:
            if self.texture_type!='Cube':
                raise RuntimeError('Uenxpected error')
        else:
            raise RuntimeError('Unexpected error')        
        self.type = read_str(f)
        if self.version=='ff7r' and self.unk_int==Utexture.UBULK_FLAG[1]:
            read_null(f)
            read_null(f)
            ubulk_map_num = read_uint32(f) #bulk map num + unk_map_num
        self.unk_map_num=read_uint32(f) #number of some mipmaps in uexp
        map_num = read_uint32(f) #map num ?

        if self.version=='ff7r':
            #ff7r have all mipmap data in a mipmap object
            self.uexp_mip_bulk = Umipmap.read(f, 'ff7r_bulk')
            read_const_uint32(f, self.cube_flag)
            f.seek(4, 1) #uexp mip map num

        #read mipmaps
        self.mipmaps = [Umipmap.read(f, self.version) for i in range(map_num)]
        _, ubulk_map_num = self.get_mipmap_num()
        self.has_ubulk=ubulk_map_num>0

        #get format name
        if self.type not in PF_FORMAT:
            raise RuntimeError('Unsupported format. ({})'.format(self.type))
        self.format_name = PF_FORMAT[self.type]
        self.byte_per_pixel = BYTE_PER_PIXEL[self.format_name]

        if self.version=='ff7r':
            #split mipmap data
            i=0
            for mip in self.mipmaps:
                if mip.uexp:
                    size = int(mip.pixel_num*self.byte_per_pixel*self.cube_flag)
                    mip.data = self.uexp_mip_bulk.data[i:i+size]
                    i+=size
            check(i, len(self.uexp_mip_bulk.data))

    #get max size of uexp mips
    def get_max_size(self):
        for mip in self.mipmaps:
            if mip.uexp:
                break
        return mip.width, mip.height

    #get number of mipmaps
    def get_mipmap_num(self):
        uexp_map_num = 0
        ubulk_map_num = 0
        for mip in self.mipmaps:
            uexp_map_num+=mip.uexp
            ubulk_map_num+=not mip.uexp
        return uexp_map_num, ubulk_map_num

    #save as uasset
    def save(self, file):
        folder = os.path.dirname(file)
        if folder not in ['.', ''] and not os.path.exists(folder):
            mkdir(folder)

        uasset_name, uexp_name, ubulk_name = get_all_file_path(file)
        if not self.has_ubulk:
            ubulk_name = None
        
        #write .uexp
        with open(uexp_name, 'wb') as f:
            
            self.write_uexp(f)
            if self.version=='4.27':
                write_null(f)
            
            write_uint64(f, self.none_name_id)
            
            f.write(Utexture.UNREAL_SIGNATURE)
            size = f.tell()
            f.seek(self.offset_to_end_offset)
            write_uint32(f, self.uasset_size+size-12)

        #write .ubulk if exist
        if self.has_ubulk:
            with open(ubulk_name, 'wb') as f:
                for mip in self.mipmaps:
                    if not mip.uexp:
                        f.write(mip.data)

        #write .uasset        
        self.uasset.exports[0].update(size -4, size -4)
        self.uasset.save(uasset_name, size)
        return uasset_name, uexp_name, ubulk_name

    def write_uexp(self, f):
        #get mipmap info
        max_width, max_height = self.get_max_size()
        uexp_map_num, ubulk_map_num = self.get_mipmap_num()
        uexp_map_data_size = 0
        for mip in self.mipmaps:
            if mip.uexp:
                uexp_map_data_size += len(mip.data)+32*(self.version!='ff7r')
        
        #write cooked size if exist
        if self.bin1 is not None:
            self.original_height=max(self.original_height, max_height)
            self.original_width=max(self.original_width, max_width)
            f.write(self.bin1)
            write_uint32(f, self.original_width)
            write_uint32(f, self.original_height)
        else:
            self.original_height=max_height
            self.original_width =max_width

        f.write(self.unk)

        #write meta data
        write_uint64(f, self.type_name_id)
        write_uint32(f, 0) #write dummy offset. (rewrite it later)
        if self.version in ['4.27', 'bloodstained']:
            write_null(f)
        
        write_uint32(f, self.original_width)
        write_uint32(f, self.original_height)
        write_uint16(f, self.cube_flag)
        write_uint16(f, self.unk_int)

        write_str(f, self.type)

        if self.version=='ff7r' and self.unk_int==Utexture.UBULK_FLAG[1]:
            write_null(f)
            write_null(f)
            write_uint32(f, ubulk_map_num+self.unk_map_num)
        
        write_uint32(f, self.unk_map_num)
        write_uint32(f, len(self.mipmaps))

        if self.version=='ff7r':
            #pack mipmaps in a mipmap object
            uexp_bulk=b''
            for mip in self.mipmaps:
                if mip.uexp:
                    uexp_bulk = b''.join([uexp_bulk, mip.data])
            size = self.get_max_size()
            self.uexp_mip_bulk=Umipmap('ff7r_bulk')
            self.uexp_mip_bulk.update(uexp_bulk, size, True)
            self.uexp_mip_bulk.offset=self.uasset_size+f.tell()+24
            self.uexp_mip_bulk.write(f, self.uasset_size)

            write_uint32(f, self.cube_flag)
            write_uint32(f, uexp_map_num)
        
        if self.version in ['4.27', 'ff7r']:
            offset = 0
        else:
            new_end_offset = self.uasset_size+f.tell() + uexp_map_data_size+ubulk_map_num*32 + (len(self.mipmaps))*(self.version=='bloodstained')*4
            offset = -new_end_offset-8
        #write mipmaps
        for mip in self.mipmaps:
            if mip.uexp:
                mip.offset=self.uasset_size+f.tell()+24
            else:
                mip.offset=offset
                offset+=mip.data_size
            mip.write(f, self.uasset_size)

    #remove mipmaps except the largest one
    def remove_mipmaps(self):
        old_mipmap_num = len(self.mipmaps)
        self.mipmaps = [self.mipmaps[0]]
        self.mipmaps[0].uexp=True
        self.has_ubulk=False
        print('mipmaps have been removed.')
        print('  mipmap: {} -> 1'.format(old_mipmap_num))

    #inject dds into asset
    def inject_dds(self, dds, force=False):
        #check formats
        if '(signed)' in dds.header.format_name:
            raise RuntimeError('UE4 requires unsigned format but your dds is {}.'.format(dds.header.format_name))

        if dds.header.format_name!=self.format_name and not force:
            raise RuntimeError('The format does not match. ({}, {})'.format(self.type, dds.header.format_name))

        if dds.header.texture_type!=self.texture_type:
            raise RuntimeError('Texture type does not match. ({}, {})'.format(self.texture_type, dds.header.texture_type))
        
        '''
        def get_key_from_value(d, val):
            keys = [k for k, v in d.items() if v == val]
            if keys:
                return keys[0]
            return None

        if force:
            self.format_name = dds.header.format_name
            new_type = get_key_from_value(self.format_name)
            self.uasset_size+=len(new_type)-len(self.type)
            self.type = new_type
            self.name_list[self.type_name_id]=self.type
            self.byte_per_pixel = BYTE_PER_PIXEL[self.format_name]
        '''
            
        max_width, max_height = self.get_max_size()
        old_size = (max_width, max_height)
        old_mipmap_num = len(self.mipmaps)

        #inject
        i=0
        self.mipmaps=[Umipmap(self.version) for i in range(len(dds.mipmap_data))]
        for data, size, mip in zip(dds.mipmap_data, dds.mipmap_size, self.mipmaps):
            if self.has_ubulk and i+1<len(dds.mipmap_data) and size[0]*size[1]>=1024**2:
                mip.update(data, size, False)
            else:
                mip.update(data, size, True)
            i+=1

        #print results
        max_width, max_height = self.get_max_size()
        new_size = (max_width, max_height)
        _, ubulk_map_num = self.get_mipmap_num()
        if ubulk_map_num==0:
            self.has_ubulk=False
        new_mipmap_num = len(self.mipmaps)

        print('dds has been injected.')
        print('  size: {} -> {}'.format(old_size, new_size))
        print('  mipmap: {} -> {}'.format(old_mipmap_num, new_mipmap_num))
        
        #warnings
        if new_mipmap_num>1 and (not is_power_of_2(max_width) or not is_power_of_2(max_height)):
            print('Warning: Mipmaps should have power of 2 as its width and height. ({}, {})'.format(max_width, max_height))
        if new_mipmap_num>1 and old_mipmap_num==1:
            print('Warning: The original texture has only 1 mipmap. But your dds has multiple mipmaps.')
            

    def print(self, verbose=False):
        if verbose:
            i=0
            for mip in self.mipmaps:
                print('  Mipmap {}'.format(i))
                mip.print(padding=4)
                i+=1
        if self.bin1 is not None:
            print('  original_width: {}'.format(self.original_width))
            print('  original_height: {}'.format(self.original_height))
        print('  format: {}'.format(self.type))
        print('  texture type: {}'.format(self.texture_type))
        print('  mipmap num: {}'.format(len(self.mipmaps)))
