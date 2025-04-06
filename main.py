import os # this is for pkgrip
import subprocess # this is for pkgrip
import warnings
from pathlib import Path
import sys
import time
import xml.etree.ElementTree 

import requests

try:
    from humanize import naturalsize
except ModuleNotFoundError as e:
    warnings.warn(f'{type(e).__name__}: {e}, consider `{Path(sys.executable).name} -m pip install humanize` to get prettier statuses')
    naturalsize = lambda num,format,binary: f'{x} Bytes'
    
PS3P_PKG_RIPPER_LOCATION = Path(__file__).parent / 'PS3P_PKG_Ripper.exe' if os.name == 'nt' else 0/0
DOWNLOAD_FILE_CHUNK_SIZE = 8192
AMNT_OF_CHUNKS_TILL_DOWNLOAD_BAR_UPDATE = 10_000

ASCII_LETTERS = frozenset('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
ASCII_NUMBERS = frozenset('0123456789')

def move_folder_or_file(src_folder: Path, dst_folder: Path) -> None:
    """
    it will make a new folder with the `.name` of `src_folder` in `dst_folder` if it does not exist there, otherwise itll merge
    """

    proper_dst_folder = dst_folder / src_folder.name 

    if src_folder.is_file():
        src_folder.replace(proper_dst_folder)
        return

    proper_dst_folder.mkdir(exist_ok=True)

    for file in src_folder.rglob('*'):
        dst_file = proper_dst_folder / file.relative_to(src_folder)
        if file.is_dir():
            dst_file.mkdir(exist_ok=True,parents=True)
        elif file.is_file():
            file.replace(dst_file)
        else:
            raise ValueError(f'tf is a {file}')


def extract_pkg(pkg: Path, output_location: Path):
    result = subprocess.run((PS3P_PKG_RIPPER_LOCATION,'-o',output_location,pkg),capture_output=True)
    if result.returncode:
        raise ValueError(f'{result.stdout} {result.stderr}')


def pretty_bytes(num: int, fmt: str = "%f") -> str:
    binary_n = naturalsize(num, format=fmt, binary=True)
    if 'Byte' in binary_n:
        return binary_n
    number,unit = binary_n.split(' ')
    pretty_number: float | int = float(number)
    if pretty_number.is_integer():
        pretty_number = int(pretty_number)
    binary_n = f'{pretty_number} {unit}'
    
    power_of_10_n = naturalsize(num, format=fmt, binary=False)
    number,unit = power_of_10_n.split(' ')
    pretty_number = float(number)
    if pretty_number.is_integer():
        pretty_number = int(pretty_number)
    power_of_10_n = f'{pretty_number} {unit}'
    
    return power_of_10_n if len(binary_n) > len(power_of_10_n) else binary_n

def get_app_ver_and_catergory_offsets_and_values(param_sfo: Path) -> tuple[str,int,str,int]:
    """
    super lazy implementation lmao
    """
    version_str: str | None = None
    version_offset: int | None = None
    catergory_str: str | None = None
    catergory_offset: int | None = None
    with open(param_sfo,'rb') as f:
        if f.read(4) != b'\x00PSF':
            raise ValueError(f'Invalid param.sfo magic in {ps3_game_dir}')
        
        param_sfo_version = int.from_bytes(f.read(4),'little')
        key_table_start = int.from_bytes(f.read(4),'little')
        data_table_start = int.from_bytes(f.read(4),'little')
        tables_entries_num = int.from_bytes(f.read(4),'little')
        
        back_here = f.tell()
        for _ in range(tables_entries_num):
            f.seek(back_here)
            key_offset = int.from_bytes(f.read(2),'little')
            data_fmt = int.from_bytes(f.read(2),'little')
            data_len = int.from_bytes(f.read(4),'little')
            data_max_len = int.from_bytes(f.read(4),'little')
            data_offset = int.from_bytes(f.read(4),'little')
            back_here = f.tell()

            if data_fmt != 0x204: # UTF-8
                continue            


            f.seek(key_table_start + key_offset)
            key = b''.join(iter(lambda: f.read(1),b'\x00')).decode('utf-8')
            if key == 'APP_VER':
                version_offset = data_table_start+data_offset
                f.seek(version_offset)
                version_str = b''.join(iter(lambda: f.read(1),b'\x00')).decode('utf-8')
            elif key == 'CATEGORY':
                catergory_offset = data_table_start+data_offset
                f.seek(catergory_offset)
                catergory_str = b''.join(iter(lambda: f.read(1),b'\x00')).decode('utf-8')

    if any(x is None for x in (version_str,version_offset,catergory_str,catergory_offset)):
        raise ValueError(f'Missing stuff in {param_sfo}')
    
    return version_str,version_offset,catergory_str,catergory_offset


def validate_title_id(title_id: str) -> str:
    if len(title_id) != 9:
        raise ValueError(f'Invalid {title_id = }')

    title_id = title_id.upper()
    
    if set(title_id[:4]) - ASCII_LETTERS:
        raise ValueError(f'Invalid {title_id = } maybe its a homebrew title id?')

    if set(title_id[4:]) - ASCII_NUMBERS:
        raise ValueError(f'Invalid {title_id = }  maybe its a homebrew title id?')
    
    return title_id


def get_pkg_links(title_id: str) -> list[str]:
    url = f'https://a0.ww.np.dl.playstation.net/tpl/np/{title_id}/{title_id}-ver.xml'

    requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    with requests.get(url,verify=False) as r:
        if r.status_code == 404:
            raise ValueError(f'Got 404 for {title_id}, likley means there are no updates for this game, or you misstyped the title id')
        r.raise_for_status()
        pkg_links_xml = xml.etree.ElementTree.fromstring(r.content)

    return [package_link_xml.attrib['url'] 
            for child in pkg_links_xml 
                for package_link_xml in child 
                    if package_link_xml.tag == 'package']


def main() -> int:
    temp_pkg_path = Path(r'temp_dl_update.pkg')
    output_pkgs_extract_location = Path(r'temp_pkgs_extract')
    title_id = 'BCES01423'
    disc_dump_folder = Path(r'lbpk uk disc jb folder')
    
    ### TODO put in arg parsing here
    
    ps3_game_dir = disc_dump_folder / 'PS3_GAME'
    
    old_version,old_version_offset,old_catergory,old_catergory_offset = get_app_ver_and_catergory_offsets_and_values(ps3_game_dir / 'PARAM.SFO')
    
    if old_catergory != 'DG':
        raise ValueError(f'PARAM.SFO in {ps3_game_dir} CATEGORY is {old_catergory}, not DG, maybe wrong param.sfo?')
    
    output_pkgs_extract_location.mkdir(exist_ok=True)
    
    title_id = validate_title_id(title_id)
    print('Grabbing pkg links')
    start_time = time.perf_counter()
    pkg_links = get_pkg_links(title_id)
    print(f'Took {time.perf_counter() - start_time} seconds')
    if not pkg_links:
        raise ValueError(f'no pkg updates found for {title_id}')
    # pkg_links = []
    start_extracting_pkgs_time = time.perf_counter()
    for i,pkg_link in enumerate(pkg_links):
        with requests.get(pkg_link, stream=True) as r:
            r.raise_for_status()
            content_size = int(r.headers['Content-Length'])
            pretty_size = pretty_bytes(content_size)
            previous_size_of_line = 0
            progress_downloaded = 0
            start_time = time.perf_counter()
            print(f'Start downloading pkg {i+1}/{len(pkg_links)} ({pkg_link})')
            print(f'0/{pretty_size}',end='\r')
            with open(temp_pkg_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=DOWNLOAD_FILE_CHUNK_SIZE):
                    progress_downloaded += len(chunk)
                    if not progress_downloaded % AMNT_OF_CHUNKS_TILL_DOWNLOAD_BAR_UPDATE:
                        pretty_print_status = f'{pretty_bytes(progress_downloaded)}/{pretty_size} elasped {time.perf_counter() - start_time} seconds'
                        
                        print(pretty_print_status.ljust(previous_size_of_line),end='\r')
                        previous_size_of_line = len(pretty_print_status)
                    f.write(chunk)


            pretty_print_status = f'{pretty_bytes(progress_downloaded)}/{pretty_size} elasped {time.perf_counter() - start_time} seconds'
            print(pretty_print_status.ljust(previous_size_of_line),end='\r')
            print()
            
            start_time = time.perf_counter()
            print(f'Extracting to {output_pkgs_extract_location} (output muted)')
            extract_pkg(temp_pkg_path,output_pkgs_extract_location)
            print(f'Took {time.perf_counter() - start_time} seconds')
            
    print(f'Done downloading and extracting the pkgs, took {time.perf_counter() - start_extracting_pkgs_time} seconds')

    new_version,_,_,_ = get_app_ver_and_catergory_offsets_and_values(output_pkgs_extract_location / 'PARAM.SFO')
    
    print(f'editing param.sfo in {ps3_game_dir}')
    
    with open(ps3_game_dir / 'PARAM.SFO','rb+') as f:
        # TODO, this assumes that the new values are same length (not inlcuding null bytes)
        f.seek(old_version_offset)
        f.write(new_version.encode('utf-8'))
        
        f.seek(old_catergory_offset)
        f.write(b'HG')
    print('param.sfo modifed')
    
    start_moving_stuff_time = time.perf_counter()
    print(f'Moving stuff from {output_pkgs_extract_location} to {ps3_game_dir}')
    
    for entry in output_pkgs_extract_location.iterdir():
        # break
        if entry.name.upper() == 'PARAM.SFO':
            continue
        move_folder_or_file(entry,ps3_game_dir)
    
    print(f'Took {time.perf_counter() - start_moving_stuff_time} seconds')
    
    new_title_id_folder = ps3_game_dir.rename(ps3_game_dir.parent / title_id)
    
    print(f'Complete!, pack {new_title_id_folder} to pkg, or copy it to /dev_hdd0/game and rebuild database after copy')
    
    return 0


if __name__ == '__main__':
    raise SystemExit(main())