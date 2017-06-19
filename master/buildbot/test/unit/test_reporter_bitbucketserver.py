# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

from __future__ import absolute_import
from __future__ import print_function
from future.utils import PY3

from mock import Mock

from twisted.internet import defer
from twisted.trial import unittest

from buildbot import config
from buildbot.process.results import FAILURE
from buildbot.process.results import SUCCESS
from buildbot.reporters.bitbucketserver import BitbucketServerPRCommentPush
from buildbot.reporters.bitbucketserver import BitbucketServerStatusPush
from buildbot.test.fake import httpclientservice as fakehttpclientservice
from buildbot.test.fake import fakemaster
from buildbot.test.util.logging import LoggingMixin
from buildbot.test.util.notifier import NotifierTestMixin
from buildbot.test.util.reporter import ReporterTestMixin


class TestBitbucketServerStatusPush(unittest.TestCase, ReporterTestMixin, LoggingMixin):

    @defer.inlineCallbacks
    def setupReporter(self, **kwargs):
        # ignore config error if txrequests is not installed
        self.patch(config, '_errors', Mock())
        self.master = fakemaster.make_master(
            testcase=self, wantData=True, wantDb=True, wantMq=True)

        self._http = yield fakehttpclientservice.HTTPClientService.getFakeService(
            self.master, self,
            'serv', auth=('username', 'passwd'),
            debug=None, verify=None)
        self.sp = sp = BitbucketServerStatusPush("serv", "username", "passwd", **kwargs)
        yield sp.setServiceParent(self.master)
        yield self.master.startService()

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.master.stopService()

    @defer.inlineCallbacks
    def setupBuildResults(self, buildResults):
        self.insertTestData([buildResults], buildResults)
        build = yield self.master.data.get(("builds", 20))
        defer.returnValue(build)

    @defer.inlineCallbacks
    def test_basic(self):
        self.setupReporter()
        build = yield self.setupBuildResults(SUCCESS)
        # we make sure proper calls to txrequests have been made
        self._http.expect(
            'post',
            u'/rest/build-status/1.0/commits/d34db33fd43db33f',
            json={'url': 'http://localhost:8080/#builders/79/builds/0',
                  'state': 'INPROGRESS', 'key': u'Builder0',
                  'description': 'Build started.'})
        self._http.expect(
            'post',
            u'/rest/build-status/1.0/commits/d34db33fd43db33f',
            json={'url': 'http://localhost:8080/#builders/79/builds/0',
                  'state': 'SUCCESSFUL', 'key': u'Builder0',
                  'description': 'Build done.'})
        self._http.expect(
            'post',
            u'/rest/build-status/1.0/commits/d34db33fd43db33f',
            json={'url': 'http://localhost:8080/#builders/79/builds/0',
                  'state': 'FAILED', 'key': u'Builder0',
                  'description': 'Build done.'})
        build['complete'] = False
        self.sp.buildStarted(("build", 20, "started"), build)
        build['complete'] = True
        self.sp.buildFinished(("build", 20, "finished"), build)
        build['results'] = FAILURE
        self.sp.buildFinished(("build", 20, "finished"), build)

    @defer.inlineCallbacks
    def test_setting_options(self):
        self.setupReporter(statusName='Build', startDescription='Build started.',
                           endDescription='Build finished.')
        build = yield self.setupBuildResults(SUCCESS)
        # we make sure proper calls to txrequests have been made
        self._http.expect(
            'post',
            u'/rest/build-status/1.0/commits/d34db33fd43db33f',
            json={'url': 'http://localhost:8080/#builders/79/builds/0',
                  'state': 'INPROGRESS', 'key': u'Builder0',
                  'name': 'Build', 'description': 'Build started.'})
        self._http.expect(
            'post',
            u'/rest/build-status/1.0/commits/d34db33fd43db33f',
            json={'url': 'http://localhost:8080/#builders/79/builds/0',
                  'state': 'SUCCESSFUL', 'key': u'Builder0',
                  'name': 'Build', 'description': 'Build finished.'})
        self._http.expect(
            'post',
            u'/rest/build-status/1.0/commits/d34db33fd43db33f',
            json={'url': 'http://localhost:8080/#builders/79/builds/0',
                  'state': 'FAILED', 'key': u'Builder0',
                  'name': 'Build', 'description': 'Build finished.'})
        build['complete'] = False
        self.sp.buildStarted(("build", 20, "started"), build)
        build['complete'] = True
        self.sp.buildFinished(("build", 20, "finished"), build)
        build['results'] = FAILURE
        self.sp.buildFinished(("build", 20, "finished"), build)

    @defer.inlineCallbacks
    def test_error(self):
        self.setupReporter()
        build = yield self.setupBuildResults(SUCCESS)
        # we make sure proper calls to txrequests have been made
        self._http.expect(
            'post',
            u'/rest/build-status/1.0/commits/d34db33fd43db33f',
            json={'url': 'http://localhost:8080/#builders/79/builds/0',
                  'state': 'INPROGRESS', 'key': u'Builder0',
                  'description': 'Build started.'},
            code=404,
            content_json={
                "error_description": "This commit is unknown to us",
                "error": "invalid_commit"})
        build['complete'] = False
        self.setUpLogging()
        self.sp.buildStarted(("build", 20, "started"), build)
        self.assertLogged('404: Unable to send Bitbucket Server status')


UNICODE_BODY = u"body: \u00E5\u00E4\u00F6 text"
EXPECTED_API = u'/rest/api/1.0/projects/PRO/repos/myrepo/pull-requests/20/comments'
PR_URL = "http://example.com/projects/PRO/repos/myrepo/pull-requests/20"


class TestBitbucketServerPRCommentPush(unittest.TestCase, NotifierTestMixin, LoggingMixin):

    @defer.inlineCallbacks
    def setupReporter(self, **kwargs):
        # ignore config error if txrequests is not installed
        self.patch(config, '_errors', Mock())
        self.master = fakemaster.make_master(
            testcase=self, wantData=True, wantDb=True, wantMq=True)

        self._http = yield fakehttpclientservice.HTTPClientService.getFakeService(
            self.master, self, 'serv', auth=('username', 'passwd'), debug=None,
            verify=None)
        self.cp = BitbucketServerPRCommentPush("serv", "username", "passwd", **kwargs)
        yield self.cp.setServiceParent(self.master)
        yield self.master.startService()
        self.cp.messageFormatter = Mock(spec=self.cp.messageFormatter)
        self.cp.messageFormatter.formatMessageForBuildResults.return_value = \
            {"body": UNICODE_BODY,
             "type": "text"}

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.master.stopService()

    @defer.inlineCallbacks
    def setupBuildResults(self, buildResults, set_pr=True):
        buildset, builds = yield NotifierTestMixin.setupBuildResults(self, buildResults)
        if set_pr:
            self.master.db.builds.setBuildProperty(
                20, "pullrequesturl", PR_URL, "test")
        defer.returnValue((buildset, builds))

    @defer.inlineCallbacks
    def test_reporter_basic(self):
        yield self.setupReporter()
        _, builds = yield self.setupBuildResults(SUCCESS)
        build = builds[0]
        self._http.expect(
            "post",
            EXPECTED_API,
            json={"text": UNICODE_BODY},
            code=201)
        build["complete"] = True
        self.cp.buildComplete(("build", 20, "finished"), build)

    @defer.inlineCallbacks
    def test_reporter_non_unicode(self):
        if PY3:
            raise unittest.SkipTest("not supported in Python3")
        yield self.setupReporter()

        self.cp.messageFormatter.formatMessageForBuildResults.return_value = \
            {"body": "body text",
             "type": "text"}

        _, builds = yield self.setupBuildResults(SUCCESS)
        build = builds[0]
        self._http.expect(
            "post",
            EXPECTED_API,
            json={"text": "body text"},
            code=201)
        build["complete"] = True
        self.cp.buildComplete(("build", 20, "finished"), build)

    @defer.inlineCallbacks
    def test_reporter_without_pullrequest(self):
        yield self.setupReporter()
        _, builds = yield self.setupBuildResults(SUCCESS, set_pr=False)
        build = builds[0]
        build["complete"] = True
        # we don't expect any request
        self.cp.buildComplete(("builds", 20, "finished"), build)

    @defer.inlineCallbacks
    def test_reporter_with_buildset(self):
        yield self.setupReporter(buildSetSummary=True)
        buildset, _ = yield self.setupBuildResults(SUCCESS)
        self._http.expect(
            "post",
            EXPECTED_API,
            json={"text": UNICODE_BODY},
            code=201)
        self.cp.buildsetComplete(("buildsets", 20, "complete"), buildset)

    @defer.inlineCallbacks
    def test_reporter_on_invalid_return_code(self):
        yield self.setupReporter()
        _, builds = yield self.setupBuildResults(SUCCESS)
        build = builds[0]
        self._http.expect(
            "post",
            EXPECTED_API,
            json={"text": UNICODE_BODY},
            code=404,
            content_json=None)
        self.setUpLogging()
        build['complete'] = True
        self.cp.buildComplete(("builds", 20, "finished"), build)
        self.assertLogged('404: Unable to send a comment: None')
