# This file is part of Buildbot. Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

from twisted.internet import defer
from twisted.logger import Logger

from buildbot.interfaces import LatentWorkerFailedToSubstantiate
from buildbot.util import kubeclientservice
from buildbot.util.latent import CompatibleLatentWorkerMixin
from buildbot.worker.docker import DockerBaseWorker

log = Logger()


class KubeLatentWorker(CompatibleLatentWorkerMixin,
                       DockerBaseWorker):

    instance = None
    _kube = None

    @defer.inlineCallbacks
    def getPodSpec(self, build):
        image = yield build.render(self.image)
        env = yield self.createEnvironment(build)

        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": self.getContainerName()
            },
            "spec": {
                "affinity": (yield self.get_affinity(build)),
                "containers": [{
                    "name": self.getContainerName(),
                    "image": image,
                    "env": [{
                        "name": k,
                        "value": v
                    } for k, v in env.items()],
                    "resources": (yield self.getBuildContainerResources(build)),
                    "volumeMounts": (yield self.get_build_container_volume_mounts(build)),
                }] + (yield self.getServicesContainers(build)),
                "nodeSelector": (yield self.get_node_selector(build)),
                "restartPolicy": "Never",
                "volumes": (yield self.get_volumes(build)),
            }
        }

    def getBuildContainerResources(self, build):
        # customization point to generate Build container resources
        return {}

    def get_build_container_volume_mounts(self, build):
        return []

    def get_affinity(self, build):
        return {}

    def get_node_selector(self, build):
        return {}

    def get_volumes(self, build):
        return []

    def getServicesContainers(self, build):
        # customization point to create services containers around the build container
        # those containers will run within the same localhost as the build container (aka within
        # the same pod)
        return []

    def renderWorkerProps(self, build_props):
        return self.getPodSpec(build_props)

    def checkConfig(self,
                    name,
                    image='buildbot/buildbot-worker',
                    namespace=None,
                    masterFQDN=None,
                    kube_config=None,
                    **kwargs):

        super().checkConfig(name, None, **kwargs)
        # Check if KubeClientService supports the given configuration
        kubeclientservice.KubeClientService(kube_config=kube_config)

    @defer.inlineCallbacks
    def reconfigService(self,
                        name,
                        image='buildbot/buildbot-worker',
                        namespace=None,
                        masterFQDN=None,
                        kube_config=None,
                        **kwargs):

        # Set build_wait_timeout to 0 if not explicitly set: Starting a
        # container is almost immediate, we can afford doing so for each build.
        if 'build_wait_timeout' not in kwargs:
            kwargs['build_wait_timeout'] = 0
        if masterFQDN is None:
            masterFQDN = self.get_ip
        if callable(masterFQDN):
            masterFQDN = masterFQDN()
        if self._kube is not None:
            yield self._kube.disownServiceParent()
        yield super().reconfigService(name, image=image, masterFQDN=masterFQDN, **kwargs)
        self._kube = kubeclientservice.KubeClientService(kube_config=kube_config)
        yield self._kube.setServiceParent(self.master)
        yield self._kube.reconfigService(kube_config=kube_config)

        self.namespace = namespace or self._kube.namespace

    @defer.inlineCallbacks
    def start_instance(self, build):
        try:
            yield self.stop_instance(reportFailure=False)
            pod_spec = yield self.renderWorkerPropsOnStart(build)
            yield self._kube.createPod(self.namespace, pod_spec)
        except kubeclientservice.KubeError as e:
            raise LatentWorkerFailedToSubstantiate(str(e)) from e
        return True

    @defer.inlineCallbacks
    def stop_instance(self, fast=False, reportFailure=True):
        self.current_pod_spec = None
        self.resetWorkerPropsOnStop()
        try:
            yield self._kube.deletePod(self.namespace, self.getContainerName())
        except kubeclientservice.KubeJsonError as e:
            if reportFailure and e.reason != 'NotFound':
                raise
        if fast:
            return
        yield self._kube.waitForPodDeletion(
            self.namespace,
            self.getContainerName(),
            timeout=self.missing_timeout)
