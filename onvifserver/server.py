#! -*- coding:utf-8 -*-
#
# Copyright 2017 , donglin-zhang, Hangzhou, China
#
# Licensed under the GNU GENERAL PUBLIC LICENSE, Version 3.0;
# you may not use this file except in compliance with the License.
#
import socketserver
import sys
from http.server import BaseHTTPRequestHandler
import re
import traceback
import inspect
from onvifserver.utils import soap_decode, soap_encode


class OnvifServerDispatcher(object):
    '''
    onvif服务端任务分发处理模块，根据不同请求url路径将消息分发至对应的模块中
    '''
    def __init__(self, allow_none=False, encoding=None, use_builtin_types=False):
        self.funcs = {}
        self.instances = {}
        self.allow_none = allow_none
        self.encoding = encoding or 'utf-8'
        self.use_builtin_types = use_builtin_types

    def register_instance(self, instance_dict, allow_dotted_names=False):
        """
        注册一个对象来响应对应的onvif请求
        参数：
            instance_dict：{service_path: instance}
        """
        self.instances.update(instance_dict)
        self.allow_dotted_names = allow_dotted_names

    def register_function(self, function, name=None):
        """Registers a function to respond to XML-RPC requests.

        The optional name argument can be used to set a Unicode name
        for the function.
        """

        if name is None:
            name = function.__name__
        self.funcs[name] = function

    def _marshaled_dispatch(self, data, dispatch_method = None, path = None):
        """
        Todo
        """
        try:
            method, params = soap_decode(data)
            # generate response
            if dispatch_method is not None:
                response = dispatch_method(method, params, path)
            else:
                response = self._dispatch(method, params, path)
            # wrap response in a singleton tuple
            # response = (response,)
            response = soap_encode(response, method, path)
        # except Fault as fault:
        #     response = dumps(fault, allow_none=self.allow_none,
        #                      encoding=self.encoding)
        except:
            # report exception back to server
            exc_type, exc_value, exc_tb = sys.exc_info()
            # response = soap_encode(
            #     Fault(1, "%s:%s" % (exc_type, exc_value)),
            #     encoding=self.encoding, allow_none=self.allow_none,
            #     )
        # return response
        return response.encode(self.encoding, 'xmlcharrefreplace')

    def _dispatch(self, method, params, path):
        """
        dsf
        """
        func = None
        try:
            # check to see if a matching function has been registered
            func = self.funcs[method]
        except KeyError:
            try:
                instance = self.instances[path]
            except KeyError:
                pass
            else:
                if hasattr(instance, '_dispatch'):
                    return instance._dispatch(method, params)
                else:
                    # todo
                    pass
        if func is not None:
            return func(params)
        else:
            raise Exception('method "%s" is not supported' % method)


class OnvifServerRequestHandler(BaseHTTPRequestHandler):
    """Simple XML-RPC request handler class.

    Handles all HTTP POST requests and attempts to decode them as
    XML-RPC requests.
    """

    # Class attribute listing the accessible path components;
    # paths not on this list will result in a 404 error.
    service_paths = ('/onvif/device_service', '/onvif/media')

    #if not None, encode responses larger than this, if possible
    encode_threshold = 1400 #a common MTU

    #Override form StreamRequestHandler: full buffering of output
    #and no Nagle.
    wbufsize = -1
    disable_nagle_algorithm = True

    # a re to match a gzip Accept-Encoding
    aepattern = re.compile(r"""
                            \s* ([^\s;]+) \s*            #content-coding
                            (;\s* q \s*=\s* ([0-9\.]+))? #q
                            """, re.VERBOSE | re.IGNORECASE)

    def accept_encodings(self):
        r = {}
        ae = self.headers.get("Accept-Encoding", "")
        for e in ae.split(","):
            match = self.aepattern.match(e)
            if match:
                v = match.group(3)
                v = float(v) if v else 1.0
                r[match.group(1)] = v
        return r

    def is_rpc_path_valid(self):
        if self.service_paths:
            return self.path in self.service_paths
        else:
            # If .rpc_paths is empty, just assume all paths are legal
            return True

    def do_POST(self):
        """Handles the HTTP POST request.

        Attempts to interpret all HTTP POST requests as XML-RPC calls,
        which are forwarded to the server's _dispatch method for handling.
        """

        # Check that the path is legal
        if not self.is_rpc_path_valid():
            self.report_404()
            return

        try:
            # Get arguments by reading body of request.
            # We read this in chunks to avoid straining
            # socket.read(); around the 10 or 15Mb mark, some platforms
            # begin to have problems (bug #792570).
            max_chunk_size = 10*1024*1024
            size_remaining = int(self.headers["content-length"])
            L = []
            while size_remaining:
                chunk_size = min(size_remaining, max_chunk_size)
                chunk = self.rfile.read(chunk_size)
                if not chunk:
                    break
                L.append(chunk)
                size_remaining -= len(L[-1])
            data = b''.join(L)

            data = self.decode_request_content(data)
            if data is None:
                return #response has been sent

            # In previous versions of SimpleXMLRPCServer, _dispatch
            # could be overridden in this class, instead of in
            # SimpleXMLRPCDispatcher. To maintain backwards compatibility,
            # check to see if a subclass implements _dispatch and dispatch
            # using that method if present.
            response = self.server._marshaled_dispatch(
                    data, getattr(self, '_dispatch', None), self.path
                )
        except Exception as e: # This should only happen if the module is buggy
            # internal error, report as HTTP server error
            self.send_response(500)

            # Send information about the exception if requested
            if hasattr(self.server, '_send_traceback_header') and \
                    self.server._send_traceback_header:
                self.send_header("X-exception", str(e))
                trace = traceback.format_exc()
                trace = str(trace.encode('ASCII', 'backslashreplace'), 'ASCII')
                self.send_header("X-traceback", trace)

            self.send_header("Content-length", "0")
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Connection", "close")
            self.send_header("Content-type", "application/soap+xml; charset=utf-8")
            # if self.encode_threshold is not None:
            #     if len(response) > self.encode_threshold:
            #         q = self.accept_encodings().get("gzip", 0)
            #         if q:
            #             try:
            #                 response = gzip_encode(response)
            #                 self.send_header("Content-Encoding", "gzip")
            #             except NotImplementedError:
            #                 pass
            self.send_header("Content-length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    def decode_request_content(self, data):
        '''
        检测消息内容是否为soap+xml消息
        '''
        #support gzip encoding of request
        content_type = self.headers.get("content-type", "unknown").lower()
        if content_type == "unknown":
            self.send_response(501, "unknown content-type")
        if  "application/soap+xml" in content_type:
            try:
                return data
            except NotImplementedError:
                self.send_response(501, "content_type %r not supported" % content_type)
            except ValueError:
                self.send_response(400, "error decoding soap content")
        else:
            self.send_response(501, "content-type %r not supported" % content_type)
        self.send_header("Content-length", "0")
        self.end_headers()

    def report_404 (self):
        # Report a 404 error
        self.send_response(404)
        response = b'No such page'
        self.send_header("Content-type", "text/plain")
        self.send_header("Content-length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_request(self, code='-', size='-'):
        """Selectively log an accepted request."""

        if self.server.logRequests:
            BaseHTTPRequestHandler.log_request(self, code, size)


class OnvifServer(socketserver.TCPServer, OnvifServerDispatcher):
    """
    基于python socketserver，参考xmlRPC.server搭建的soap webservice框架，
    用于实现onvif server端业务, 框架提供创建创建webservice，并处理客户端请
    求的功能，上层应用只需要实现业务操作的相关接口即可，例如下面的代码实现了
    ONVIF摄像机GetDeviceInformation功能：
    from onvifserver.server import OnvifServer

    with OnvifServer(("192.168.1.9", 8000)) as server:
        server.register_introspection_functions()

        def get_device_info_function(a):
            device_info = {'manufacturer': 'GOSUN',
                            'Firmware_Version': 'V5.4.0 build 160613',
                            'Model': 'DS-2DE72XYZIW-ABC/VS'}
            return device_info
        server.register_function(get_device_info_function, "GetDeviceInformation")
        server.serve_forever()
    """

    allow_reuse_address = True

    # Warning: this is for debugging purposes only! Never set this to True in
    # production code, as will be sending out sensitive information (exception
    # and stack trace details) when exceptions are raised inside
    # SimpleXMLRPCRequestHandler.do_POST
    _send_traceback_header = False

    def __init__(self, addr, requestHandler=OnvifServerRequestHandler,
                 logRequests=True, allow_none=False, encoding=None,
                 bind_and_activate=True, use_builtin_types=False):
        self.logRequests = logRequests
        self.dispatchers = {}
        OnvifServerDispatcher.__init__(self, allow_none, encoding, use_builtin_types)
        socketserver.TCPServer.__init__(self, addr, requestHandler, bind_and_activate)
