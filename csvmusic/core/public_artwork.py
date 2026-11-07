# tabs only
"""Fetch untrusted CSV artwork without granting access to private networks."""
import ipaddress
import socket
from urllib.parse import urlsplit, urljoin

import certifi
import urllib3


MAX_ARTWORK_BYTES = 10 * 1024 * 1024


def public_artwork_bytes(url: str) -> bytes | None:
	"""Validate every hop and connect to a validated IP, avoiding DNS rebinding."""
	try:
		for _ in range(4):
			parts = urlsplit(url)
			if parts.scheme not in ("https", "http") or not parts.hostname or parts.username is not None or parts.password is not None:
				return None
			host = parts.hostname.encode("idna").decode("ascii")
			port = parts.port or (443 if parts.scheme == "https" else 80)
			if port != (443 if parts.scheme == "https" else 80):
				return None
			addresses = [row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]
			if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
				return None
			options = {"timeout": urllib3.Timeout(connect=5, read=12)}
			if parts.scheme == "https":
				pool = urllib3.HTTPSConnectionPool(addresses[0], port, server_hostname=host, assert_hostname=host, cert_reqs="CERT_REQUIRED", ca_certs=certifi.where(), **options)
			else:
				pool = urllib3.HTTPConnectionPool(addresses[0], port, **options)
			try:
				target = parts.path or "/"
				if parts.query:
					target += "?" + parts.query
				response = pool.request("GET", target, headers={"Host": host, "Accept": "image/*"}, redirect=False, retries=False, preload_content=False)
				try:
					if response.status in (301, 302, 303, 307, 308):
						location = response.headers.get("Location")
						if not location:
							return None
						url = urljoin(url, location)
						continue
					if response.status != 200 or not response.headers.get("Content-Type", "").lower().startswith("image/"):
						return None
					if int(response.headers.get("Content-Length", "0")) > MAX_ARTWORK_BYTES:
						return None
					body = response.read(MAX_ARTWORK_BYTES + 1, decode_content=False)
					return body if body and len(body) <= MAX_ARTWORK_BYTES else None
				finally:
					response.close()
			finally:
				pool.close()
	except Exception:
		# Never log an untrusted URL: query strings can contain credentials.
		return None
	return None
