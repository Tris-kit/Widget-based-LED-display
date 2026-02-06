import board
import digitalio


def init_status_led() -> digitalio.DigitalInOut:
    """Initialize the onboard status LED, if available."""
    led = digitalio.DigitalInOut(board.LED)
    led.direction = digitalio.Direction.OUTPUT
    return led


def blink_error(led: digitalio.DigitalInOut) -> None:
    """Turn the status LED on to indicate an error."""
    if led is None:
        return
    led.value = True


def toggle_led(led: digitalio.DigitalInOut, value: bool) -> None:
    """Set the status LED to the provided boolean value."""
    if led is None:
        return
    led.value = value
