"""Bounded, iterative object-graph snapshots for the pinned in-memory engine."""
from array import array
from collections import Counter,OrderedDict,defaultdict,deque
from datetime import date,datetime
from enum import Enum
import base64
import importlib
import json
import math
import types
import typing

ALLOWED_MODULES=('builtins','array','collections','datetime','enum','math','copy',
    'Common','KLine','Bi','Seg','ZS','BuySellPoint','Math','ChanModel','ChanConfig','chanmodel','workbench',
    'workbench.incremental','chanmodel.reference_engine','typing')
MAX_NODES=5_000_000


def _global(value):
    module=getattr(value,'__module__',None)
    name=getattr(value,'__qualname__',None)
    if not module or not name or '<locals>' in name:
        raise ValueError('engine snapshot contains a non-importable runtime global')
    if not (module in ALLOWED_MODULES or any(module.startswith(prefix+'.') for prefix in ALLOWED_MODULES
                                             if prefix not in {'builtins','array','collections','datetime','enum','math','copy'})):
        raise ValueError('engine snapshot global module is outside the pinned allow-list: '+module)
    return {'global':[module,name]}


def graph_dumps(root):
    identities={};nodes=[];pending=[]
    def ref(value):
        if value is None or type(value) in (str,bool,int):return value
        if type(value) is float:
            if math.isnan(value):return {'float':'nan'}
            if value==math.inf:return {'float':'inf'}
            if value==-math.inf:return {'float':'-inf'}
            return value
        if isinstance(value,Enum):return {'enum':[_global(type(value)),value.name]}
        if isinstance(value,typing.TypeVar):return {'typevar':[value.__module__,value.__name__]}
        if isinstance(value,bytes):return {'bytes':base64.b64encode(value).decode('ascii')}
        if isinstance(value,datetime):return {'datetime':value.isoformat()}
        if isinstance(value,date):return {'date':value.isoformat()}
        if isinstance(value,slice):return {'slice':[ref(value.start),ref(value.stop),ref(value.step)]}
        if isinstance(value,tuple):return {'tuple':[ref(item) for item in value]}
        if isinstance(value,frozenset):return {'frozenset':[ref(item) for item in value]}
        if isinstance(value,types.MethodType):
            return {'method':[ref(value.__self__),_global(value.__func__)]}
        if isinstance(value,(types.FunctionType,types.BuiltinFunctionType,type,types.BuiltinMethodType,
                             types.MethodDescriptorType,types.WrapperDescriptorType,types.GetSetDescriptorType,
                             types.MemberDescriptorType,property,classmethod,staticmethod)):
            return _global(value)
        identity=id(value)
        if identity in identities:return {'ref':identities[identity]}
        index=len(nodes)
        if index>=MAX_NODES:raise ValueError('engine snapshot object count exceeds limit')
        identities[identity]=index;nodes.append(None);pending.append((index,value))
        return {'ref':index}
    root_ref=ref(root)
    cursor=0
    while cursor<len(pending):
        index,value=pending[cursor];cursor+=1
        if isinstance(value,list):
            node={'kind':'list','items':[ref(x) for x in value]}
        elif isinstance(value,OrderedDict):
            node={'kind':'mapping','class':_global(type(value)),'items':[[ref(k),ref(v)] for k,v in value.items()]}
        elif isinstance(value,Counter):
            node={'kind':'mapping','class':_global(type(value)),'items':[[ref(k),ref(v)] for k,v in value.items()]}
        elif isinstance(value,defaultdict):
            node={'kind':'defaultdict','class':_global(type(value)),'factory':ref(value.default_factory),
                  'items':[[ref(k),ref(v)] for k,v in value.items()]}
        elif isinstance(value,dict):
            node={'kind':'mapping','class':_global(type(value)),'items':[[ref(k),ref(v)] for k,v in value.items()]}
        elif isinstance(value,set):
            node={'kind':'set','items':[ref(x) for x in value]}
        elif isinstance(value,deque):
            node={'kind':'deque','maxlen':value.maxlen,'items':[ref(x) for x in value]}
        elif isinstance(value,array):
            node={'kind':'array','typecode':value.typecode,'items':[ref(float(x)) if value.typecode in 'fd' else int(x) for x in value]}
        else:
            cls=type(value);attrs={}
            try:attrs.update(vars(value))
            except TypeError:pass
            slots=[]
            for base in cls.__mro__:
                declared=getattr(base,'__slots__',())
                if isinstance(declared,str):declared=(declared,)
                for name in declared:
                    if name in {'__dict__','__weakref__'} or name in attrs:continue
                    try:attrs[name]=getattr(value,name);slots.append(name)
                    except AttributeError:pass
            node={'kind':'object','class':_global(cls),'attrs':[[name,ref(item)] for name,item in attrs.items()],
                  'slots':slots}
        nodes[index]=node
    return json.dumps({'schema':1,'root':root_ref,'nodes':nodes},ensure_ascii=False,
                      allow_nan=False,separators=(',',':')).encode('utf-8')


def graph_loads(payload,*,max_bytes=256*1024*1024):
    if len(payload)>max_bytes:raise ValueError('engine snapshot exceeds byte limit')
    graph=json.loads(payload)
    if graph.get('schema')!=1 or not isinstance(graph.get('nodes'),list) or len(graph['nodes'])>MAX_NODES:
        raise ValueError('engine snapshot schema/node count invalid')
    nodes=graph['nodes'];values=[None]*len(nodes)
    def global_value(tag):
        module,name=tag['global']
        if not (module in ALLOWED_MODULES or any(module.startswith(prefix+'.') for prefix in ALLOWED_MODULES
                                                 if prefix not in {'builtins','array','collections','datetime','enum','math','copy'})):
            raise ValueError('snapshot global is outside the pinned allow-list')
        value=importlib.import_module(module)
        for part in name.split('.'):value=getattr(value,part)
        return value
    def read(value):
        if isinstance(value,(str,int,float,bool)) or value is None:return value
        if not isinstance(value,dict) or len(value)!=1:raise ValueError('invalid snapshot value tag')
        if 'ref' in value:
            index=value['ref']
            if type(index) is not int or not 0<=index<len(values):raise ValueError('snapshot reference out of range')
            return values[index]
        if 'global' in value:return global_value(value)
        if 'typevar' in value:
            module,name=value['typevar'];value=getattr(importlib.import_module(module),name)
            if not isinstance(value,typing.TypeVar):raise ValueError('snapshot TypeVar does not match its module binding')
            return value
        if 'float' in value:return {'nan':float('nan'),'inf':float('inf'),'-inf':-float('inf')}[value['float']]
        if 'enum' in value:return global_value(value['enum'][0])[value['enum'][1]]
        if 'bytes' in value:return base64.b64decode(value['bytes'],validate=True)
        if 'datetime' in value:return datetime.fromisoformat(value['datetime'])
        if 'date' in value:return date.fromisoformat(value['date'])
        if 'slice' in value:return slice(*(read(x) for x in value['slice']))
        if 'tuple' in value:return tuple(read(x) for x in value['tuple'])
        if 'frozenset' in value:return frozenset(read(x) for x in value['frozenset'])
        if 'method' in value:return read(value['method'][1]).__get__(read(value['method'][0]),type(read(value['method'][0])))
        raise ValueError('unknown engine snapshot value tag')
    for index,node in enumerate(nodes):
        kind=node.get('kind')
        if kind=='list':values[index]=[]
        elif kind=='mapping':
            cls=global_value(node['class']);values[index]=cls()
        elif kind=='defaultdict':
            cls=global_value(node['class']);values[index]=cls(read(node['factory']))
        elif kind=='set':values[index]=set()
        elif kind=='deque':values[index]=deque(maxlen=node.get('maxlen'))
        elif kind=='array':values[index]=array(node['typecode'])
        elif kind=='object':
            cls=global_value(node['class'])
            try:values[index]=object.__new__(cls)
            except TypeError as exc:raise ValueError('snapshot type cannot be allocated safely: '+cls.__name__) from exc
        else:raise ValueError('unknown engine snapshot node kind')
    for index,node in enumerate(nodes):
        target=values[index];kind=node['kind']
        if kind=='list':target.extend(read(x) for x in node['items'])
        elif kind in {'mapping','defaultdict'}:
            for key,value in node['items']:target[read(key)]=read(value)
        elif kind=='set':target.update(read(x) for x in node['items'])
        elif kind=='deque':target.extend(read(x) for x in node['items'])
        elif kind=='array':target.extend(read(x) if isinstance(x,dict) else x for x in node['items'])
        elif kind=='object':
            attrs={name:read(value) for name,value in node['attrs']}
            if hasattr(target,'__dict__'):object.__getattribute__(target,'__dict__').update(attrs)
            for name in node['slots']:object.__setattr__(target,name,attrs[name])
    return read(graph['root'])

