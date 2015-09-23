"""
Credits:
* https://code.google.com/p/webscraping/source/browse/webkit.py
* https://github.com/jeanphix/Ghost.py/blob/master/ghost/ghost.py
"""
'''
from PyQt5.QtCore import QEventLoop, QUrl, QEventLoop, QTimer, QByteArray, QSize
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWebKitWidgets import QWebView, QWebPage
from PyQt5.QtNetwork import (QNetworkAccessManager, QNetworkRequest,
                             QNetworkCookieJar, QNetworkCookie)
from PyQt5.QtCore import qInstallMessageHandler
from PyQt5.QtCore import QtDebugMsg, QtWarningMsg, QtCriticalMsg, QtFatalMsg
'''
from PyQt4.QtCore import QEventLoop, QUrl, QEventLoop, QTimer, QByteArray, QSize
from PyQt4.QtGui import QApplication
from PyQt4.QtWebKit import QWebView, QWebPage
from PyQt4.QtNetwork import (QNetworkAccessManager, QNetworkRequest,
                             QNetworkCookieJar, QNetworkCookie)
from PyQt4.QtCore import qInstallMsgHandler
from PyQt4.QtCore import QtDebugMsg, QtWarningMsg, QtCriticalMsg, QtFatalMsg
import logging
from six.moves.urllib.parse import urlsplit
from weblib.encoding import decode_dict
import six
import time
from collections import Counter

from wkit.network import WKitNetworkAccessManager
from wkit.error import WKitError
from wkit.logger import configure_logger
from wkit.document import Document

logger = logging.getLogger('wkit')


class QTMessageProxy(object):
    def __init__(self, logger):
        self.logger = logger

    def __call__(self, msgType, wtf, msg):
        #print('1)', msgType)
        #print('2)', msg)
        #print('3)', zz)
        levels = {
            QtDebugMsg: 'debug',
            QtWarningMsg: 'warn',
            QtCriticalMsg: 'critical',
            QtFatalMsg: 'fatal',
        }
        getattr(self.logger, levels[msgType])(msg)


qt_logger = configure_logger('qt', 'QT', logging.DEBUG, logging.StreamHandler())
qInstallMsgHandler(QTMessageProxy(qt_logger))


class HttpResource(object):
    def __init__(self, reply):
        self.url = str(reply.url().toString())
        self.status_code = \
            reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        if not isinstance(self.status_code, int):
            self.status_code = self.status_code.toInt()[0]
        self.headers = {}
        for header in reply.rawHeaderList():
            self.headers[header.data()] = bytes(reply.rawHeader(header))
        try:
            self.content = reply.data
        except AttributeError:
            self.content = reply.readAll()


class WKitWebView(QWebView):
    def setApplication(self, app):
        self.app = app

    def closeEvent(self, event):
        self.app.quit()

    def sizeHint(self):
        viewport_size = (800, 600)
        return QSize(*viewport_size)


class WKitWebPage(QWebPage):
    def __init__(self, *args, **kwargs):
        QWebPage.__init__(self)
        self.user_agent = 'QtWebKitWrapper'

    def userAgentForUrl(self, url):
        if self.user_agent is None:
            return super(WebPage, self).userAgentForUrl(url)
        else:
            return self.user_agent

    def shouldInterruptJavaScript(self):
        return True

    def javaScriptAlert(self, frame, msg):
        logger.error('JS ALERT: %s' % msg) 
    def javaScriptConfirm(self, frame, msg):
        logger.error('JS CONFIRM: %s' % msg)

    def javaScriptPrompt(self, frame, msg, default):
        logger.error('JS PROMPT: %s' % msg)

    def javaScriptConsoleMessage(self, msg, line_number, src_id):
        logger.error('JS CONSOLE MSG: %s' % msg)


class Browser(object):
    _app = None

    def __init__(self, gui=False):
        if not Browser._app:
            Browser._app = QApplication([])

        self.manager = WKitNetworkAccessManager()
        self.manager.finished.connect(self.handle_finished_network_reply)

        self.cookie_jar = QNetworkCookieJar()
        self.manager.setCookieJar(self.cookie_jar)

        self.page = WKitWebPage()
        self.page.setNetworkAccessManager(self.manager)

        self.view = WKitWebView()
        self.view.setPage(self.page)
        self.view.setApplication(Browser._app)

        if gui:
            self.view.show()

    def get_cookies(self):
        cookies = {}
        for cookie in self.cookie_jar.allCookies():
            cookies[cookie.name().data()] = cookie.value().data()
        return cookies

    def go(self, url, **kwargs):
        return self.request(url=url, **kwargs)

    def request(self, url=None, user_agent='Mozilla', cookies=None, timeout=10,
                method='get', data=None, headers=None, proxy=None):
        if cookies is None:
            cookies = {}
        if headers is None:
            headers = {}
        url_info = urlsplit(url)

        self.resource_list = []
        loop = QEventLoop()
        self.view.loadFinished.connect(loop.quit)

        if proxy:
            self.manager.setup_proxy(proxy)

        # Timeout
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(timeout * 1000)

        # User-Agent
        self.page.user_agent = user_agent

        # Cookies
        cookie_obj_list = []
        for name, value in cookies.items():
            domain = ('.' + url_info.netloc).split(':')[0]
            #print 'CREATE COOKIE %s=%s' % (name, value)
            #print 'DOMAIN = %s' % domain
            cookie_obj = QNetworkCookie(name, value)
            cookie_obj.setDomain(domain)
            cookie_obj_list.append(cookie_obj)
        #self.cookie_jar.setAllCookies(cookie_obj_list)

        # Method
        method_obj = getattr(QNetworkAccessManager, '%sOperation'
                             % method.capitalize())

        # Ensure that Content-Type is correct if method is post
        if method == 'post':
            headers['Content-Type'] = 'application/x-www-form-urlencoded'

        # Post data
        if data is None:
            data = QByteArray()

        # Request object
        request_obj = QNetworkRequest(QUrl(url))

        # Headers
        for name, value in headers.items():
            request_obj.setRawHeader(name, value)

        # Make a request
        self.content_type_stats = Counter()
        self.view.load(request_obj, method_obj, data)

        loop.exec_()

        if timer.isActive():
            request_resource = None
            url = str(self.page.mainFrame().url().toString()).rstrip('/')
            for res in self.resource_list:
                if url == res.url or url == res.url.rstrip('/'):
                    request_resource = res
                    break
            if request_resource:
                return self.build_document(request_resource)
            else:
                raise WKitError('Request was successful but it is not possible'
                                ' to associate the request to one of received'
                                ' responses')
        else:
            raise WKitError('Timeout while loading %s' % url)

    def build_document(self, res):
        doc = Document()
        doc.body = res.content
        doc.status_code = res.status_code
        doc.url = res.url
        doc.headers = decode_dict(res.headers)
        doc.cookies = decode_dict(self.get_cookies())
        doc.parse()
        doc.page = self.page
        return doc

    #def __del__(self):
    #    self.view.setPage(None)

    def handle_finished_network_reply(self, reply):
        status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        if status_code:
            if not isinstance(status_code, int):
                status_code = status_code.toInt()[0]
            logger.debug('HttpResource [%d]: %s' % (status_code,
                                                reply.url().toString()))
            try:
                data = reply.data
            except AttributeError:
                data = reply.readAll()
            self.resource_list.append(HttpResource(reply))
            ctype = reply.rawHeader('Content-Type').data()\
                         .decode('latin').split(';')[0]
            self.content_type_stats[ctype] += 1
