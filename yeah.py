from gevent import monkey; monkey.patch_all()
from gevent.pywsgi import WSGIServer
from optparse import OptionParser
from httplib import HTTPConnection
from urlparse import urlparse
import re
import logging
import copy
import urllib

class YeahHTTPConnection(HTTPConnection):
    def _send_output(self, message_body=None):
        self._buffer.extend(("", ""))
        for msg in self._buffer:
            self.send(msg + "\r\n")
        del self._buffer[:]

        if message_body is not None:
            self.send(message_body)

class YeahProxy(object):
    def __init__(self, host, port, pool, timeout, domains):
        self.host = host
        self.port = port
        self.pool = pool
        self.timeout = timeout
        self.proxy_hosts = domains

    def serve_forever(self):
        logging.info('PROXY START FOR %r', self.proxy_hosts)
        self.wsgi_server = WSGIServer((self.host, self.port),
                                      self.yeahp_application,
                                      spawn=self.pool)
        self.wsgi_server.serve_forever()

    def yeahp_application(self, env, start_response):
        if env['PATH_INFO'] == '/wpad.dat':
            start_response('200 OK',
                        [('Content-Type', 'application/x-ns-proxy-autoconfig')])

            return ['%s\r\n' % l for l in self.get_pac()]
        else:
            return self.yeah(env, start_response)

    def get_pac(self):
        yield 'function FindProxyForURL(url, host) {'
        yield '  __proxy_hosts = ["%s"];' % ('", "'.join(self.proxy_hosts))
        yield '  if (url.substring(0,5) == "http:") {'
        yield '    for ( var i = 0 ; i < __proxy_hosts.length; i++) {'
        yield '      if (shExpMatch(host, __proxy_hosts[i])) {'
        yield '        return "PROXY %s:%d"' % (self.host, self.port)
        yield '      }'
        yield '    }'
        yield '  }'
        yield '}'

    def yeah(self, env, start_response):
        logging.debug(env)
        def fix_url():
            url = env['PATH_INFO']
            if env.get('QUERY_STRING'):
                url += '?%s' % env['QUERY_STRING']

            env['fixed_url'] = url

        fix_url()
        logging.debug('Process proxy request: %s', env['fixed_url'])

        _proxy_hdrs = dict({})
        for k in env:
            if k.startswith('HTTP_'):
                _key = k.replace('HTTP_', '', 1)
                if _key.startswith('PROXY_'):
                    continue
                _key = re.sub(r"(^|_)(.)",
                              lambda m: m.group(0).upper(),
                              _key.swapcase()).replace('_', '-')
                _proxy_hdrs[_key] = env[k]
        logging.debug(_proxy_hdrs)

        _proxy_body = None
        if env.get('CONTENT_LENGTH'):
            _length = int(env['CONTENT_LENGTH'])
            _proxy_body = env['wsgi.input'].read(_length)
            logging.debug('POST BODY: %s' % _proxy_body)

        if env.get('CONTENT_TYPE'):
            _proxy_hdrs['content-type'] = env.get('CONTENT_TYPE')

        try:
            _ru = urlparse(env['fixed_url'])
            _rp = '%s%s' % (urllib.quote(_ru.path), '?' + _ru.query if len(_ru.query) > 0 else '')
            logging.info('PROXY %s %s %s' % (env['REQUEST_METHOD'], _ru.netloc, _rp))
            _request_c = YeahHTTPConnection(_ru.netloc, timeout=self.timeout)
            _request_c.request(env['REQUEST_METHOD'],
                               _rp,
                               body=_proxy_body,
                               headers=_proxy_hdrs)
            _rr = _request_c.getresponse()
        except:
            start_response("501 Gateway error", [('Content-Type', 'text/html')])
            logging.exception('Proxy request error')
            return ['<h1>Proxy request error</h1>']

        try:
            _rr_h = copy.copy(_rr.getheaders())

            for _hdr in _rr_h:
                if _hdr[0] == 'transfer-encoding':
                    _rr_h.remove(_hdr)

            start_response('%s %s' % (_rr.status, _rr.reason), _rr_h)
            logging.info('PROXY-RESPONSE %s -> %s(%r)' % (_rp, _rr.status, _rr.length))
            logging.debug('PROXY-RESPONSE %r' % _rr_h)
            return [_rr.read(_rr.length)]
        finally:
            _request_c.close()

def main():
    parser = OptionParser(description='Yeah!',
                          usage='Usage: %prog [options] domain1 domain2 ...')
    parser.add_option('-H', '--host', default='127.0.0.1',
                      help='Host to listen [%default]')
    parser.add_option('-p', '--port', type='int', default=8088,
                      help='Port to listen [%default]')
    parser.add_option('-P', '--pool', type='int', default=8,
                      help='Set pool size [%default]')
    parser.add_option('-t', '--timeout', type='int', default=30,
                      help='Set request timeout')
    parser.add_option('-v', '--verbose', action='store_true',
                      help='Set logger level to debug')

    options, args = parser.parse_args()
    if options.verbose:
        _logger_level = logging.DEBUG
    else:
        _logger_level = logging.INFO
    logging.basicConfig(level=_logger_level)

    ypx = YeahProxy(options.host, options.port,
                    options.pool, timeout=options.timeout,
                    domains=args)
    try:
        ypx.serve_forever()
    except KeyboardInterrupt:
        print 'exit'

if __name__ == '__main__':
    main()
