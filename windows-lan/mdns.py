"""Optional IPv4 mDNS publication, owned by the existing launcher process."""
import random
import socket
import threading
import time

from lan_address import validate_mdns


class Publisher:
    def __init__(self):
        self.zc = self.info = self.listener = None
        self.conflict = threading.Event()
        self.status = 'disabled'
        self.error = ''
        self.target = None
        self.retry_at = 0

    def close(self):
        zc, self.zc = self.zc, None
        self.info = self.listener = None
        if zc:
            try:
                zc.close()  # Withdraws registered services and their address records.
            except Exception as exc:
                print(f'mDNS cleanup: {exc}', flush=True)

    def sync(self, cfg, addresses=None):
        enabled, name = validate_mdns(cfg)
        target = (cfg['teacher_ip'], cfg['http_port'], name) if enabled else None
        if target is None:
            self.close()
            self.target, self.status = None, 'disabled'
            return
        if addresses is not None and cfg['teacher_ip'] not in addresses:
            self.close()
            self.target, self.status = None, 'offline'
            return
        if self.conflict.is_set() and self.zc:
            self.close()
            self.status, self.error = 'conflict', f'{name}.local is already in use.'
            print('mDNS: ' + self.error + ' Using the IP address.', flush=True)
        if target == self.target and (self.zc or self.status == 'conflict' or time.monotonic() < self.retry_at):
            return
        self.close()
        self.target = target
        self.conflict.clear()
        try:
            self._publish(*target)
            self.status, self.error = 'published', ''
        except Exception as exc:
            self.close()
            self.status = 'conflict' if self.conflict.is_set() else 'unavailable'
            self.error = str(exc)
            self.retry_at = time.monotonic() + 30
            print(f'mDNS unavailable: {exc}. Using the IP address.', flush=True)

    def _publish(self, ip, port, name):
        from zeroconf import (DNSAddress, DNSOutgoing, DNSQuestion, IPVersion,
                              RecordUpdateListener, ServiceInfo, Zeroconf)
        host = name + '.local.'
        packed = socket.inet_aton(ip)
        conflict = self.conflict

        class HostGuard(RecordUpdateListener):
            def async_update_records(self, zc, now, records):
                for update in records:
                    record = update.new
                    if (record.name.lower() == host and record.ttl > 0
                            and record.type in (1, 28)
                            and getattr(record, 'address', None) != packed):
                        conflict.set()

        self.zc = Zeroconf(interfaces=[ip], ip_version=IPVersion.V4Only)
        self.listener = HostGuard()
        # Service registration only checks the DNS-SD instance name. Probe the
        # actual hostname separately and monitor later conflicting A/AAAA records.
        self.zc.add_listener(self.listener, None)
        time.sleep(random.uniform(0, .25))
        for _ in range(3):
            query = DNSOutgoing(0)
            query.add_question(DNSQuestion(host, 255, 0x8001))
            # 0.151.5's helper is typed as PTR-only, but its DNS writer accepts
            # arbitrary DNSRecord objects in the authority section.
            query.authorities.append(DNSAddress(host, 1, 1, 120, packed))
            self.zc.send(query)
            if conflict.wait(.25):
                raise RuntimeError(f'{host} hostname conflict')
        self.info = ServiceInfo('_http._tcp.local.', f'{name}._http._tcp.local.',
                                server=host, addresses=[packed], port=port,
                                properties={'path': '/'}, host_ttl=30, other_ttl=30)
        self.zc.register_service(self.info, allow_name_change=False)
        if conflict.is_set():
            raise RuntimeError(f'{host} hostname conflict')

    def publication(self, cfg):
        return dict(teacher_ip=cfg['teacher_ip'], http_port=cfg['http_port'],
                    mdns_hostname=cfg.get('mdns_hostname', 'live'),
                    mdns_status=self.status)
