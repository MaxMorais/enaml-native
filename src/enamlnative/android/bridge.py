'''
Copyright (c) 2017, Jairus Martin.

Distributed under the terms of the MIT License.

The full license is in the file COPYING.txt, distributed with this software.

Created on June 21, 2017

@author: jrm
'''
import weakref
import msgpack
import functools
from contextlib import contextmanager
from atom.api import Atom, ForwardInstance, Dict, Property, Callable, Unicode, Tuple, Int,  Instance, set_default
from weakref import WeakValueDictionary

CACHE = WeakValueDictionary()
__global_id__ = 0


class Command:
    CREATE = "c"
    METHOD = "m"
    FIELD = "f"
    DELETE = "d"
    RESULT = "r"
    ERROR = "e"

class ExtType:
    REF = 1


def _generate_id():
    """ Generate an id for an object """
    global __global_id__
    __global_id__ += 1
    return __global_id__


def tag_object_with_id(obj):
    """ Generate and assign a id for the object"""
    obj.__id__ = _generate_id()
    CACHE[obj.__id__] = obj


def _cleanup_id(obj):
    """ Removes the object from the """
    try:
        del CACHE[obj.__id__]
    except KeyError:
        pass


def get_app_class():
    """ Avoid circular import. Probably indicates a
        poor design...
    """
    from .app import AndroidApplication
    return AndroidApplication


def encode(obj):
    """ Encode an object for proper decoding by Java
    """
    if hasattr(obj, '__javaclass__'):
        return msgpack.ExtType(ExtType.REF, msgpack.packb(obj.__id__))
    return obj


def msgpack_encoder(sig, obj):
    """ When passing a JavaBridgeObject encode it in a special way so
        it can properly be interpreted as a reference.

        TODO: This should use the object hooks for doing this automatically
    """
    #if isinstance(obj, (list, tuple)):
    #    return sig, [encode(o) for o in obj]
    return sig, encode(obj)


def dumps(data):
    """ Encodes events for sending over the bridge """
    return msgpack.dumps(data)


def loads(data):
    """ Decodes and processes events received from the bridge """
    return msgpack.loads(data)


class JavaReferenceError(ReferenceError):
    pass


def get_handler(ptr, method):
    """ Dereference the pointer and return the handler method. """
    obj = CACHE.get(ptr, None)
    if obj is None:
        raise JavaReferenceError("Reference id={} never existed or has already been destroyed"
                       .format(ptr))
    elif not hasattr(obj, method):
        raise NotImplementedError("{}.{} is not implemented.".format(obj, method))
    return obj, getattr(obj, method)


class JavaMethod(Property):
    """ Description of a method of a View (or subclass) in Java. When called, this
        serializes call, packs the arguments, and delegates handling to a bridge in Java.
    """
    __slots__ = ('__signature__', '__returns__', '__cache__')

    def __init__(self, *args, **kwargs):
        self.__returns__ = kwargs.get('returns', None)
        self.__signature__ = args
        self.__cache__ = {}  # Result cache otherwise gc cleans up
        super(JavaMethod, self).__init__(self.__fget__)

    @contextmanager
    def suppressed(self, obj):
        """ Suppress calls within this context to avoid feedback loops"""
        obj.__suppressed__[self.name] = True
        yield
        obj.__suppressed__[self.name] = False

    def __fget__(self, obj):
        f = functools.partial(self.__call__, obj)
        f.suppressed = functools.partial(self.suppressed, obj)
        return f

    def __call__(self, obj, *args, **kwargs):
        if obj.__suppressed__.get(self.name):
            return

        signature = self.__signature__

        vargs = signature and signature[-1].endswith("...")
        if not vargs and (len(args) != len(signature)):
            raise ValueError("Invalid number of arguments: Given {}, expected {}"
                             .format(args, signature))
        if vargs:
            varg = signature[-1].replace('...', '')
            bridge_args = [
                msgpack_encoder(signature[i] if i+1 < len(signature) else varg, args[i])
                for i in range(len(args))
            ]
        else:
            bridge_args = [msgpack_encoder(sig, arg) for sig, arg in zip(signature, args)]

        result = obj.__app__.create_future() if self.__returns__ else None

        if result:
            #: Store in local cache or global cache (weakref) removes it
            #: resulting in a Reference error when the result is returned
            self.__cache__[result.__id__] = result

            def resolve(r, f=result):
                #: Remove from local cache to free future
                del self.__cache__[f.__id__]

            #: Delete from the local cache once resolved.
            result.then(resolve)

        obj.__app__.send_event(
            Command.METHOD,  #: method
            obj.__id__,
            result.__id__ if result else 0,
            self.name,  #: method name
            bridge_args, #: args
            **kwargs #: kwargs to send_event
        )
        return result


class JavaField(Property):
    __slots__ = ('__signature__',)

    def __init__(self, arg):
        self.__signature__ = arg
        super(JavaField, self).__init__(self.__fget__, self.__fset__)

    def __fset__(self, obj, arg):
        obj.__app__.send_event(
            Command.FIELD,  #: method
            obj.__id__,
            self.name,  #: method name
            [msgpack_encoder(self.__signature__, arg)]  #: args
        )

    def __fget__(self, obj):
        raise NotImplementedError("Reading attributes is not yet supported")


class JavaCallback(JavaMethod):
    """ Description of a callback method of a View (or subclass) in Java. When called,
        it fires the connected callback. This is triggered when it receives an event from
        the bridge indicating the call has occured.
    """

    def __fget__(self, obj):
        f = super(JavaCallback, self).__fget__(obj)
        #: Add a method so it can be connected like in Qt
        f.connect = functools.partial(self.connect, obj)
        return f

    def __call__(self, obj, *args):
        """ Fire the callback if one is connected """
        if obj.__suppressed__.get(self.name):
            return
        callback = obj.__callbacks__.get(self.name)
        if callback:
            return callback(*args)

    def connect(self, obj, callback):
        """ Set the callback to be fired when the event occurs. """
        obj.__callbacks__[self.name] = callback


class JavaBridgeObject(Atom):
    """ A proxy to a class in java. This sends the commands over
        the bridge for execution.  The object is stored in a map
        with the given id and is valid until this object is deleted.
    Parameters
    ----------
    __id__: Int
        If an __id__ keyward argument is passed during creation,
        this will assume the object was already created and
        only a reference to the object with the given id is needed.

    """
    __slots__ = ('__weakref__',)

    #: Java Class name
    __javaclass__ = Unicode('java.lang.Object')

    #: Constructor signature
    __signature__ = Tuple()

    #: Suppressed methods / fields
    __suppressed__ = Dict()

    #: Callbacks
    __callbacks__ = Dict()

    #: Java object ID
    __id__ = Int(0, factory=_generate_id)

    #: Bridge
    __app__ = ForwardInstance(get_app_class)

    def _default___app__(self):
        return get_app_class().instance()

    def getId(self):
        return self.__id__

    def __init__(self, *args, **kwargs):
        """ Sends the event to create this View in Java """
        super(JavaBridgeObject, self).__init__(**kwargs)

        #: Send the event over the bridge to construct the view
        __id__ = kwargs.get('__id__', None)
        CACHE[self.__id__] = self
        if __id__ is None:
            self.__app__.send_event(
                Command.CREATE,  #: method
                self.__id__, #: id to assign in java
                self.__javaclass__,
                [msgpack_encoder(sig, arg) for sig, arg in zip(self.__signature__, args)],
            )

    def __del__(self):
        self.__app__.send_event(
            Command.DELETE,  #: method
            self.__id__, #: id to assign in java
        )
        _cleanup_id(self)
