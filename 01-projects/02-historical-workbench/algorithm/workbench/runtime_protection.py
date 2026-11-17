"""Authenticated embedded resource payloads using Windows CNG AES-256-GCM.

The key accompanies the executable, so this raises the cost of casual resource
copying rather than promising secrecy from a person controlling the machine.
Own algorithm modules remain bytecode in PyInstaller's PYZ archive. Browser
assets and the pinned vendor's source/provenance are intentionally inspectable.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import secrets

MAGIC=b'CLRP1\0'
NONCE_BYTES=12
TAG_BYTES=16
KEY_BYTES=32
MAX_PAYLOAD_BYTES=256*1024*1024


def installation_metadata(build):
    """Keep algorithm/source receipts in the executable, not user data files."""
    if not build.get('payload_protection'):return build
    return {name:value for name,value in build.items() if name not in {
        'code_sha256','engine_source_sha256','runtime_files_sha256',
        'runtime_immutable_files_sha256','payload_files_sha256'}}


class PayloadProtectionError(ValueError):
    pass


class _AuthenticatedCipherInfo(ctypes.Structure):
    _fields_=[('cbSize',ctypes.c_ulong),('dwInfoVersion',ctypes.c_ulong),
        ('pbNonce',ctypes.c_void_p),('cbNonce',ctypes.c_ulong),
        ('pbAuthData',ctypes.c_void_p),('cbAuthData',ctypes.c_ulong),
        ('pbTag',ctypes.c_void_p),('cbTag',ctypes.c_ulong),
        ('pbMacContext',ctypes.c_void_p),('cbMacContext',ctypes.c_ulong),
        ('cbAAD',ctypes.c_ulong),('cbData',ctypes.c_ulonglong),('dwFlags',ctypes.c_ulong)]


def _aad(metadata):
    return json.dumps(metadata,ensure_ascii=False,sort_keys=True,
        separators=(',',':'),allow_nan=False).encode('utf-8')


def _crypt(data,key,nonce,aad,tag=None):
    if os.name!='nt':raise PayloadProtectionError('protected payload requires Windows CNG')
    if not isinstance(key,bytes) or len(key)!=KEY_BYTES:raise PayloadProtectionError('invalid payload key')
    if not isinstance(nonce,bytes) or len(nonce)!=NONCE_BYTES:raise PayloadProtectionError('invalid payload nonce')
    if not isinstance(data,bytes) or len(data)>MAX_PAYLOAD_BYTES:raise PayloadProtectionError('invalid payload size')
    if tag is not None and (not isinstance(tag,bytes) or len(tag)!=TAG_BYTES):
        raise PayloadProtectionError('invalid authentication tag')
    api=ctypes.WinDLL('bcrypt.dll')
    ptr=ctypes.c_void_p;ulong=ctypes.c_ulong;p=ctypes.POINTER
    declarations={
        'BCryptOpenAlgorithmProvider':[p(ptr),ctypes.c_wchar_p,ctypes.c_wchar_p,ulong],
        'BCryptSetProperty':[ptr,ctypes.c_wchar_p,ptr,ulong,ulong],
        'BCryptGetProperty':[ptr,ctypes.c_wchar_p,ptr,ulong,p(ulong),ulong],
        'BCryptGenerateSymmetricKey':[ptr,p(ptr),ptr,ulong,ptr,ulong,ulong],
        'BCryptEncrypt':[ptr,ptr,ulong,ptr,ptr,ulong,ptr,ulong,p(ulong),ulong],
        'BCryptDecrypt':[ptr,ptr,ulong,ptr,ptr,ulong,ptr,ulong,p(ulong),ulong],
        'BCryptDestroyKey':[ptr], 'BCryptCloseAlgorithmProvider':[ptr,ulong]}
    for name,args in declarations.items():
        function=getattr(api,name);function.argtypes=args;function.restype=ctypes.c_long
    def check(code,operation):
        if code:
            raise PayloadProtectionError(f'{operation} failed (NTSTATUS 0x{code & 0xffffffff:08X})')
    algorithm=ptr();key_handle=ptr()
    try:
        check(api.BCryptOpenAlgorithmProvider(ctypes.byref(algorithm),'AES',None,0),'AES provider')
        mode=ctypes.create_unicode_buffer('ChainingModeGCM')
        check(api.BCryptSetProperty(algorithm,'ChainingMode',mode,ctypes.sizeof(mode),0),'AES-GCM mode')
        object_size=ulong();returned=ulong()
        check(api.BCryptGetProperty(algorithm,'ObjectLength',ctypes.byref(object_size),
            ctypes.sizeof(object_size),ctypes.byref(returned),0),'AES key object')
        key_object=ctypes.create_string_buffer(object_size.value)
        key_buffer=ctypes.create_string_buffer(key)
        check(api.BCryptGenerateSymmetricKey(algorithm,ctypes.byref(key_handle),key_object,
            object_size.value,key_buffer,len(key),0),'AES key creation')
        source=ctypes.create_string_buffer(data,max(1,len(data)))
        output=ctypes.create_string_buffer(max(1,len(data)))
        nonce_buffer=ctypes.create_string_buffer(nonce)
        aad_buffer=ctypes.create_string_buffer(aad,max(1,len(aad)))
        tag_buffer=ctypes.create_string_buffer(tag or b'\0'*TAG_BYTES,TAG_BYTES)
        info=_AuthenticatedCipherInfo();info.cbSize=ctypes.sizeof(info);info.dwInfoVersion=1
        info.pbNonce=ctypes.cast(nonce_buffer,ptr);info.cbNonce=len(nonce)
        info.pbAuthData=ctypes.cast(aad_buffer,ptr);info.cbAuthData=len(aad)
        info.pbTag=ctypes.cast(tag_buffer,ptr);info.cbTag=TAG_BYTES
        written=ulong()
        operation=api.BCryptDecrypt if tag is not None else api.BCryptEncrypt
        check(operation(key_handle,source,len(data),ctypes.byref(info),None,0,
            output,len(data),ctypes.byref(written),0),'AES-GCM authentication' if tag is not None else 'AES-GCM encryption')
        if written.value!=len(data):raise PayloadProtectionError('authenticated payload length mismatch')
        return output.raw[:written.value],tag_buffer.raw
    finally:
        if key_handle:api.BCryptDestroyKey(key_handle)
        if algorithm:api.BCryptCloseAlgorithmProvider(algorithm,0)


def seal_payload(plaintext,key,metadata):
    """Authenticate the compressed seed and build identity; no plaintext on disk."""
    if not isinstance(plaintext,bytes) or not plaintext or len(plaintext)>MAX_PAYLOAD_BYTES:
        raise PayloadProtectionError('invalid seed payload size')
    nonce=secrets.token_bytes(NONCE_BYTES)
    encrypted,tag=_crypt(plaintext,key,nonce,_aad(metadata))
    return MAGIC+nonce+tag+encrypted


def open_payload(sealed,key,metadata):
    if not isinstance(sealed,bytes) or not sealed.startswith(MAGIC):
        raise PayloadProtectionError('unknown protected payload format')
    head=len(MAGIC)
    if len(sealed)<=head+NONCE_BYTES+TAG_BYTES or len(sealed)>MAX_PAYLOAD_BYTES+head+NONCE_BYTES+TAG_BYTES:
        raise PayloadProtectionError('invalid protected payload size')
    nonce=sealed[head:head+NONCE_BYTES];head+=NONCE_BYTES
    tag=sealed[head:head+TAG_BYTES];head+=TAG_BYTES
    plain,_=_crypt(sealed[head:],key,nonce,_aad(metadata),tag)
    return plain


def load_embedded_payload(resources,build):
    """New encrypted resources coexist with read-only legacy ZIP support."""
    protection=build.get('payload_protection')
    if not protection:
        path=resources/'project-seed.zip';raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=build['payload_sha256']:
            raise PayloadProtectionError('内置程序资源校验失败，请重新下载EXE。')
        return raw
    if protection.get('format')!='windows-cng-aes256-gcm-v1' or protection.get('filename')!='project-seed.bin':
        raise PayloadProtectionError('内置加密资源格式不正确')
    path=resources/'project-seed.bin';raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=build['payload_sha256']:
        raise PayloadProtectionError('内置程序资源校验失败，请重新下载EXE。')
    try:
        from _chanlun_payload_key import KEY,BUILD_ID
    except ImportError as exc:
        raise PayloadProtectionError('内置资源解密组件缺失，请重新下载完整EXE。') from exc
    if BUILD_ID!=protection.get('build_id'):raise PayloadProtectionError('内置资源构建身份不匹配')
    plain=open_payload(raw,KEY,{'build_id':BUILD_ID,'version':build['version'],
        'plaintext_sha256':protection['plaintext_sha256']})
    if hashlib.sha256(plain).hexdigest()!=protection['plaintext_sha256']:
        raise PayloadProtectionError('内置程序资源解密后校验失败')
    return plain
