"""Assemble the original CAD add-in without copying any CAD vendor runtime."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent

def default_engine():
    """Support both this repository and the separate source archive layout."""
    embedded = ROOT / 'engine'
    return embedded if (embedded / 'planning_cli.py').is_file() else ROOT.parent

def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def copy_file(source, dest):
    if source.is_symlink() or not source.is_file():
        raise ValueError('Not an ordinary source file: ' + str(source))
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine', type=Path, default=default_engine(),
                   help='Engine source root; defaults to engine/ in a source archive or the parent repository')
    p.add_argument('--native', type=Path, required=True)
    p.add_argument('--launcher', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    engine, out = a.engine.resolve(), a.output.resolve()
    if out.exists():
        raise ValueError('Choose a new output directory to preserve previous packages')
    # The source whitelist deliberately excludes course drawings, private data,
    # absolute machine config, web UI, caches and proprietary components.
    modspec = importlib.util.spec_from_file_location('engine_release', engine/'build_release.py')
    mod = importlib.util.module_from_spec(modspec)
    modspec.loader.exec_module(mod)
    source = [(f.relative_to(engine), mod._public_bytes(f)) for f in mod.files(True)]
    runtime = engine/'runtime'
    manifest = json.loads((runtime/'RUNTIME-MANIFEST.json').read_text(encoding='utf-8'))
    for row in manifest['files']:
        f = (runtime/row['path']).resolve()
        if not f.is_relative_to(runtime) or f.is_symlink() or sha(f) != row['sha256']:
            raise ValueError('Runtime manifest verification failed: ' + row['path'])
    native_files = ['QingGuiAI.Cad.dll']
    launcher_files = ['QingGuiAI.Launcher.exe', 'QingGuiAI.Uninstall.exe', 'QingGuiStart.scr']
    for name in native_files:
        if not (a.native/name).is_file(): raise ValueError('Native DLL not built: '+name)
    for name in launcher_files:
        if not (a.launcher/name).is_file(): raise ValueError('Launcher not built: '+name)
    out.mkdir(parents=True)
    stage = out/'QingGuiAI.bundle'
    stage.mkdir()
    for name in ['PackageContents.xml','README.md','BUILD.md','LICENSE','NOTICE.md']:
        copy_file(ROOT/name, stage/name)
    for relative, data in source:
        dest = stage/'Contents/Engine'/relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    write_json(stage/'Contents/Engine/source-manifest.json', {'version':'0.2.0','files':[
        {'path':r.as_posix(),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()} for r,data in source]})
    for row in manifest['files']:
        copy_file(runtime/row['path'],stage/'Contents/Engine/runtime'/row['path'])
    copy_file(runtime/'RUNTIME-MANIFEST.json',stage/'Contents/Engine/runtime/RUNTIME-MANIFEST.json')
    for name in native_files:
        copy_file(a.native/name,stage/'Contents/Windows'/name)
    for name in launcher_files:
        copy_file(a.launcher/name,stage/'Contents/Launcher'/name)
    for f in a.launcher.glob('*.scr'):
        if f.name not in launcher_files: copy_file(f,stage/'Contents/Launcher'/f.name)
    deps=json.loads((runtime/'DEPENDENCIES.json').read_text(encoding='utf-8'))
    notices=['# Third-party notices','','Original native add-in, setup, launcher and planning engine: MIT (LICENSE).',
        'AutoCAD is a separate prerequisite; no Autodesk SDK DLL, executable, license or vendor add-on is redistributed.',
        'Embedded CPython: PSF license; see Contents/Engine/runtime/LICENSE.txt.',
        'Python packages retain their original license files and bundled-library notices in runtime/Lib/site-packages.',
        'Official source URLs and SHA-256: Contents/Engine/runtime/DEPENDENCIES.json.',
        'Project MIT terms do not override third-party license terms.','','| Package | Version | License metadata |','|---|---|---|']
    for row in deps['wheels']:
        lic=' '.join(str(row['license']).split()).replace('|','/')[:180]
        notices.append(f"| {row['name']} | {row['version']} | {lic} |")
    (stage/'THIRD_PARTY_NOTICES.md').write_text('\n'.join(notices)+'\n',encoding='utf-8')
    files=[{'path':f.relative_to(stage).as_posix(),'bytes':f.stat().st_size,'sha256':sha(f)}
           for f in sorted(stage.rglob('*')) if f.is_file()]
    blocked={'acmgd.dll','acdbmgd.dll','accoremgd.dll','adwindows.dll','acad.exe','lzxkgcad.exe'}
    if any(Path(r['path']).name.lower() in blocked for r in files):
        raise ValueError('A vendor runtime entered the bundle')
    write_json(stage/'BUNDLE-MANIFEST.json',{'product':'清规AI · CAD原生插件','version':'0.3.0',
        'host':'AutoCAD 2025 Windows x64 (R25.0, .NET 8 build)','files':files,'private_course_data_included':False,'vendor_runtime_included':False})
    archive=out/'QingGuiAI-CAD-0.3.0-bundle.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(stage.rglob('*')):
            if f.is_file(): z.write(f,f.relative_to(stage).as_posix())
    with zipfile.ZipFile(archive) as z:
        if z.testzip(): raise ValueError('ZIP integrity failed')
        for row in files:
            if hashlib.sha256(z.read(row['path'])).hexdigest()!=row['sha256']:
                raise ValueError('ZIP hash mismatch')
    result={'archive':str(archive),'sha256':sha(archive),'bytes':archive.stat().st_size,'files':len(files)+1,
        'engine_source_files':len(source),'runtime_files':len(manifest['files']),'bundle':str(stage)}
    write_json(out/'bundle-build.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
