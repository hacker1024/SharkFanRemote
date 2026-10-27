# Scripts

These tools may assist in reverse engineering.

## Contents

### `rf_receive_commands.py`

This script connects to an [ESPHome RF proxy](https://esphome.io/components/ir_rf_proxy)
component, and logs any remote transmissions it receives. This is useful for
both finding your remote's ID and discovering new keycodes.

Tested with a [TI CC1101](https://www.ti.com/product/CC1101).