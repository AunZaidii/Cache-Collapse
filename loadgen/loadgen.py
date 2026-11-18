"""CacheCollapse load generator.

Produces two kinds of traffic against the public endpoint, switched on/off live
from the dashboard through Redis flags:

  run:traffic = 1  -> steady, light "normal users" traffic (random products)
  run:attack  = 1  -> a burst of many concurrent requests for the SAME product
                      (product #1), i.e. the cache stampede

The burst keeps firing, so each time that product's cache entry expires the whole
burst misses at once -- which is the attack.
"""
import os
import asyncio
import random
import aiohttp
import redis

TARGET = os.getenv("TARGET_URL", "http://nginx:80")
ATTACK_HOT_PRODUCTS = 20    # the attacker hammers this many "hot" products
ATTACK_BURST = 250          # concurrent requests per burst
NORMAL_RPS = 40             # steady background requests per second

r = redis.Redis(host=os.getenv("REDIS_HOST", "redis"), port=6379, decode_responses=True)


def flag(name):
    return r.get("run:" + name) == "1"


async def hit(session, product_id):
    url = "%s/api/products/%d" % (TARGET, product_id)
    try:
        async with session.get(url) as resp:
            await resp.read()
    except Exception:
        pass  # failures are expected during an attack; the monitor counts them


async def normal_loop(session):
    """Send ~NORMAL_RPS requests/second to random products while traffic is on."""
    while True:
        if flag("traffic"):
            batch = [hit(session, random.randint(1, 100)) for _ in range(NORMAL_RPS // 10)]
            await asyncio.gather(*batch)
            await asyncio.sleep(0.1)
        else:
            await asyncio.sleep(0.2)


async def attack_loop(session):
    """Fire big simultaneous bursts at a set of hot products while the attack is on.

    The target product rotates through a small pool. Each product is re-hit less
    often than its cache lives, so every burst lands on an EXPIRED entry -> a fresh
    stampede each time, which keeps the database continuously overloaded (instead of
    one brief spike when a single product expires).
    """
    idx = 0
    while True:
        if flag("attack"):
            product_id = (idx % ATTACK_HOT_PRODUCTS) + 1
            idx += 1
            burst = [hit(session, product_id) for _ in range(ATTACK_BURST)]
            await asyncio.gather(*burst)
            await asyncio.sleep(0.05)
        else:
            await asyncio.sleep(0.2)


async def main():
    connector = aiohttp.TCPConnector(limit=ATTACK_BURST + 100)
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        await asyncio.gather(normal_loop(session), attack_loop(session))


if __name__ == "__main__":
    print("loadgen ready; waiting for commands from the dashboard...", flush=True)
    asyncio.run(main())
