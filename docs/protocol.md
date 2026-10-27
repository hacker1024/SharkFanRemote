# Shark TurboBlade RF Remote Protocol

_This may also apply to other products, but I have nothing else to test._

## Radio

- Band: 433 MHz.
- Modulation: OOK (on-off keying).

## Frame structure

A frame consists of 62 mark/space pairs:

| Section | Length | Contents |
| --- | --- | --- |
| Remote ID | 24 symbols | Remote identity, most significant bit first |
| Command | 8 symbols | Button command, most significant bit first |
| Inverted command | 8 symbols | Command XOR `0xFF`, most significant bit first |
| End symbol | 1 pair | Zero-like data symbol |
| Trailer | 20 pairs | Short marks and spaces |
| Frame separator | 1 pair | Short mark followed by space |

Remote IDs span `0x000000` through `0xFFFFFF`.

The 40 data symbols can be represented as five bytes:

```text
ID[23:16] ID[15:8] ID[7:0] COMMAND (COMMAND XOR 0xFF)
```

Example speed-up payload for remote ID `0xAABBCC`:

```text
AA BB CC 32 CD
```

## Pulse timings

A mark is RF on; a space is RF off. Use these concrete nominal durations for transmission:

| Symbol or pair | Mark | Space |
| --- | ---: | ---: |
| Data `0` | 200 µs | 1,100 µs |
| Data `1` | 700 µs | 400 µs |
| End symbol | 200 µs | 1,100 µs |
| Trailer pair, repeated 20 times | 200 µs | 900 µs |
| Frame separator | 200 µs | 5,050 µs |

This is pulse-width encoding with different space lengths for the two data values. The total symbol duration is not identical for `0` and `1`.

These timings were determined through captured recordings. The true values used by the firmware may be slightly different.

## Transmission bursts

One normal button press on a real remote sends four identical frames. Each frame already includes its separator; do not add another separator between them.

## Button commands

### Shark TurboBlade (TF202)

| Button | Command | Inverted command |
| --- | --- | --- |
| Power | `0x55` | `0xAA` |
| Specialty mode | `0x13` | `0xEC` |
| Speed up | `0x32` | `0xCD` |
| Speed down | `0x4A` | `0xB5` |
| Oscillation | `0x59` | `0xA6` |
| Timer | `0x68` | `0x97` |
| Rotate left | `0x1C` | `0xE3` |
| Rotate right | `0x34` | `0xCB` |

## Pairing

Pairing is performed by the fan learning a remote ID from an ordinary speed up transmission:

1. Hold the pairing button on the fan to enter pairing mode.
2. Send the speed up command with the desired 24-bit remote ID.
3. Use that ID for subsequent commands.

There is no separate pairing payload. The normal four-frame speed up burst is used.

Pairing with a new ID replaces the previously accepted remote identity in the observed pairing procedure. To restore a physical remote, enter pairing mode and press speed up on that remote.

## Encoder example

This Python function returns one button-press burst as signed microsecond timings, suitable for ESPHome raw transmission:

```python
def encode_button(remote_id: int, command: int) -> list[int]:
    if not 0 <= remote_id <= 0xFFFFFF:
        raise ValueError("remote_id must fit in 24 bits")
    if not 0 <= command <= 0xFF:
        raise ValueError("command must fit in 8 bits")

    payload = (
        (remote_id << 16)
        | (command << 8)
        | (command ^ 0xFF)
    )

    frame = []
    for shift in range(39, -1, -1):
        if (payload >> shift) & 1:
            frame.extend((700, -400))
        else:
            frame.extend((200, -1100))

    frame.extend((200, -1100))      # End symbol
    frame.extend([200, -900] * 20) # Trailer
    frame.extend((200, -5050))     # Frame separator

    return frame * 4
```

Positive durations are marks; negative durations are spaces. One frame contains 124 durations and a four-frame burst contains 496 durations.