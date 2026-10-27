#!/usr/bin/env python3
"""Decode 24-bit ID + command + inverted command from ESPHome RF proxies.

Install: python -m pip install aioesphomeapi
Run: python rf_receive_commands.py IP --key BASE64_KEY
Without API encryption, omit --key. Ctrl-C stops the listener.
Each API reception produces one line; repeated frames within it are collapsed.
"""
import argparse
import asyncio
from datetime import datetime
import logging
from collections.abc import Sequence
from dataclasses import dataclass


# Frame fields, in transmission order (most significant bit first).
REMOTE_ID_BITS = 24
COMMAND_BITS = 8
INVERTED_COMMAND_BITS = COMMAND_BITS
PAYLOAD_BITS = REMOTE_ID_BITS + COMMAND_BITS + INVERTED_COMMAND_BITS
BYTE_MASK = (1 << COMMAND_BITS) - 1
DURATIONS_PER_PAIR = 2
PAYLOAD_DURATIONS = PAYLOAD_BITS * DURATIONS_PER_PAIR
END_SYMBOL_DURATIONS = DURATIONS_PER_PAIR
COMMAND_FRAME_DURATIONS = PAYLOAD_DURATIONS + END_SYMBOL_DURATIONS

# Nominal microseconds from protocol.md.
# Receive tolerances allow for RF receiver edge shifts and timing jitter.
TIMING_TOLERANCE = 0.35
MINIMUM_TOLERANCE_US = 150
# The first mark in a capture is often stretched by receiver settling.
FIRST_MARK_EXTRA_US = 200


@dataclass(frozen=True)
class PulsePair:
    mark_us: int
    space_us: int


ZERO = PulsePair(mark_us=200, space_us=1100)
ONE = PulsePair(mark_us=700, space_us=400)
END = ZERO


def duration_matches(actual_us: int, nominal_us: int,
                     extra_upper_us: int = 0) -> bool:
    tolerance_us = max(MINIMUM_TOLERANCE_US, nominal_us * TIMING_TOLERANCE)
    return (nominal_us - tolerance_us <= actual_us
            <= nominal_us + tolerance_us + extra_upper_us)


def pair_matches(timings: Sequence[int], offset: int, nominal: PulsePair,
                 first_mark: bool = False) -> bool:
    """Match a positive mark followed by a negative space."""
    if offset + DURATIONS_PER_PAIR > len(timings):
        return False
    mark, space = timings[offset:offset + DURATIONS_PER_PAIR]
    extra_us = FIRST_MARK_EXTRA_US if first_mark else 0
    return (mark > 0 and space < 0
            and duration_matches(mark, nominal.mark_us, extra_us)
            and duration_matches(-space, nominal.space_us))


def decode_payload_at(timings: Sequence[int], start: int
                      ) -> tuple[int, int, int] | None:
    """Decode the data and end symbol at one candidate frame boundary."""
    payload = 0
    for bit_index in range(PAYLOAD_BITS):
        offset = start + bit_index * DURATIONS_PER_PAIR
        if pair_matches(timings, offset, ZERO, first_mark=(offset == 0)):
            bit = 0
        elif pair_matches(timings, offset, ONE):
            bit = 1
        else:
            return None
        payload = (payload << 1) | bit

    if not pair_matches(timings, start + PAYLOAD_DURATIONS, END):
        return None

    inverted_command = payload & BYTE_MASK
    command = (payload >> INVERTED_COMMAND_BITS) & BYTE_MASK
    remote_id = payload >> (COMMAND_BITS + INVERTED_COMMAND_BITS)
    if command ^ inverted_command != BYTE_MASK:
        return None
    return remote_id, command, inverted_command


def decode_commands(timings: Sequence[int]) -> list[tuple[int, int, int]]:
    """Return distinct commands in order, collapsing repeats in one reception.

    Scan candidate boundaries to tolerate partial frames at capture edges.
    Decode the 40 data bits and end symbol; trailer/separator timings are not
    required, so both single-frame and whole-burst captures can be read.
    """
    commands = []
    offset = 0
    while offset + COMMAND_FRAME_DURATIONS <= len(timings):
        command = decode_payload_at(timings, offset)
        if command is None:
            offset += 1
            continue
        if command not in commands:
            commands.append(command)
        offset += COMMAND_FRAME_DURATIONS
    return commands


async def listen(args):
    from aioesphomeapi import APIClient, RadioFrequencyInfo

    while True:
        disconnected = asyncio.Event()
        client = APIClient(args.ip, args.port, None, noise_psk=args.key)
        unsubscribe = None
        try:
            async def on_stop(expected):
                disconnected.set()

            await client.connect(on_stop=on_stop, login=True)
            entities, _ = await client.list_entities_services()
            receivers = {
                (e.device_id, e.key): e.name
                for e in entities
                if isinstance(e, RadioFrequencyInfo) and e.capabilities & 2
                and (args.receiver is None or e.object_id == args.receiver)
            }
            if not receivers:
                raise ValueError('No matching RF receive proxy found')

            def receive(event):
                if (event.device_id, event.key) not in receivers:
                    return
                payloads = decode_commands(event.timings)
                if not payloads:
                    return
                fields = []
                for remote_id, command, inverted in payloads:
                    fields.append(
                        f'remote_id=0x{remote_id:06X} command=0x{command:02X} '
                        f'inverted_command=0x{inverted:02X} '
                        f'inverse_ok={str(command ^ inverted == 0xFF).lower()}'
                    )
                print(datetime.now().astimezone().isoformat(timespec='seconds')
                      + ' ' + ' ; '.join(fields), flush=True)

            unsubscribe = client.subscribe_infrared_rf_receive(receive)
            logging.info('Listening on %s: %s', args.ip, ', '.join(receivers.values()))
            await disconnected.wait()
        except ValueError:
            raise
        except Exception as error:
            # Avoid logging connection arguments, which include the API key.
            logging.warning('Connection interrupted (%s); retrying in 3 seconds',
                            type(error).__name__)
        finally:
            if unsubscribe:
                unsubscribe()
            await client.disconnect()
        await asyncio.sleep(3)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('ip', help='ESPHome device IP address or hostname')
    parser.add_argument('--key', help='Optional base64 API encryption key')
    parser.add_argument('--port', type=int, default=6053)
    parser.add_argument('--receiver', help='Optional RF receive proxy object_id')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    try:
        asyncio.run(listen(args))
    except KeyboardInterrupt:
        pass
    except (ValueError, ImportError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
