import time
try:
    from typing import Optional
except ImportError:
    from local.typing_compat import Optional

import board
import digitalio


def resolve_pin(pin_name):
    if pin_name is None:
        return None
    name = str(pin_name).strip().upper()
    if not name:
        return None
    if name.isdigit():
        name = "GP{}".format(name)
    return getattr(board, name, None)


class Button:
    def __init__(
        self,
        pin,
        name: str = "Button",
        hold_seconds: float = 3.0,
        active_low: bool = True,
        on_click=None,
        on_hold=None,
    ) -> None:
        self.pin = pin
        self.name = name or "Button"
        self.hold_seconds = hold_seconds
        self.active_low = active_low
        self.on_click = on_click
        self.on_hold = on_hold
        self._pressed = False
        self._press_start = None
        self._hold_fired = False

        self.io = digitalio.DigitalInOut(pin)
        self.io.direction = digitalio.Direction.INPUT
        if active_low:
            self.io.pull = digitalio.Pull.UP
        else:
            self.io.pull = digitalio.Pull.DOWN
        try:
            raw_value = self.io.value
            pressed = (not raw_value) if self.active_low else bool(raw_value)
            if pressed:
                print(
                    "{} reads pressed at init. Check wiring or button_active_low.".format(
                        self.name
                    )
                )
        except Exception:
            pass

    @property
    def is_pressed(self) -> bool:
        return self._pressed

    def update(self, now=None) -> None:
        if now is None:
            now = time.monotonic()
        raw_value = self.io.value
        pressed = (not raw_value) if self.active_low else bool(raw_value)

        if pressed and not self._pressed:
            self._pressed = True
            self._press_start = now
            self._hold_fired = False

        if pressed and self._pressed:
            if (
                not self._hold_fired
                and self._press_start is not None
                and (now - self._press_start) >= self.hold_seconds
            ):
                self._hold_fired = True
                if self.on_hold:
                    self.on_hold()

        if not pressed and self._pressed:
            if not self._hold_fired:
                if self.on_click:
                    self.on_click()
            self._pressed = False
            self._press_start = None
            self._hold_fired = False

    def deinit(self) -> None:
        try:
            self.io.deinit()
        except Exception:
            pass


class ButtonController:
    def __init__(
        self,
        button1_pin_name,
        button2_pin_name,
        hold_seconds: float = 3.0,
        active_low: bool = True,
        status_led=None,
        combo_hold_seconds: float = 1.0,
    ) -> None:
        self.status_led = status_led
        self.display_enabled = True
        self.display_toggle_requested = False
        self.next_widget_requested = False
        self.widget_event = None
        self.combo_hold_seconds = combo_hold_seconds
        self._combo_start = None
        self._combo_fired = False
        self._suppress_actions = False

        self.button1 = None
        self.button2 = None

        button1_pin = resolve_pin(button1_pin_name)
        button2_pin = resolve_pin(button2_pin_name)
        if button1_pin is not None:
            self.button1 = Button(
                button1_pin,
                name="Button 1",
                hold_seconds=hold_seconds,
                active_low=active_low,
                on_click=self._button1_click,
                on_hold=self._button1_hold,
            )
        if button2_pin is not None:
            self.button2 = Button(
                button2_pin,
                name="Button 2",
                hold_seconds=hold_seconds,
                active_low=active_low,
                on_click=self._button2_click,
                on_hold=self._button2_hold,
            )

    def _button1_click(self) -> None:
        if self._suppress_actions:
            return
        self.widget_event = "click"
        print("Button 1 click")

    def _button1_hold(self) -> None:
        if self._suppress_actions:
            return
        self.widget_event = "hold"
        print("Button 1 hold")

    def _button2_click(self) -> None:
        if self._suppress_actions:
            return
        self.next_widget_requested = True
        print("Button 2 click -> next widget")

    def _button2_hold(self) -> None:
        if self._suppress_actions:
            return
        self.display_enabled = not self.display_enabled
        self.display_toggle_requested = True
        state = "on" if self.display_enabled else "off"
        print("Button 2 hold -> display", state)

    def update(self, now=None) -> bool:
        if now is None:
            now = time.monotonic()
        active = False
        if self.button1 is not None:
            self.button1.update(now)
            active = active or self.button1.is_pressed
        if self.button2 is not None:
            self.button2.update(now)
            active = active or self.button2.is_pressed
        # Detect combo-press to switch widgets (both buttons held briefly).
        if self.button1 is not None and self.button2 is not None:
            if self.button1.is_pressed and self.button2.is_pressed:
                if self._combo_start is None:
                    self._combo_start = now
                    self._combo_fired = False
                elif not self._combo_fired and (now - self._combo_start) >= self.combo_hold_seconds:
                    self._combo_fired = True
                    self._suppress_actions = True
                    print("Buttons combo")
            else:
                self._combo_start = None
                if self._suppress_actions and not active:
                    self._suppress_actions = False
        if self.status_led is not None:
            try:
                self.status_led.value = active
            except Exception:
                pass
        return active

    def consume_widget_event(self) -> Optional[str]:
        if self.widget_event:
            event = self.widget_event
            self.widget_event = None
            return event
        return None

    def consume_display_toggle(self) -> Optional[bool]:
        if self.display_toggle_requested:
            self.display_toggle_requested = False
            return self.display_enabled
        return None

    def consume_next_widget_requested(self) -> bool:
        if self.next_widget_requested:
            self.next_widget_requested = False
            return True
        return False
