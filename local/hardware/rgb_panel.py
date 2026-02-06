import board
import displayio
import framebufferio
import rgbmatrix


class RgbPanel:
    def __init__(
        self,
        width: int = 64,
        height: int = 64,
        bit_depth: int = 1,
        serpentine: bool = True,
        doublebuffer: bool = True,
    ) -> None:
        # Fail loudly if RGB matrix libraries are missing.

        displayio.release_displays()

        matrix = rgbmatrix.RGBMatrix(
            width=width,
            height=height,
            bit_depth=bit_depth,
            rgb_pins=[
                board.GP2,
                board.GP3,
                board.GP4,
                board.GP5,
                board.GP8,
                board.GP9,
            ],
            addr_pins=[board.GP10, board.GP16, board.GP18, board.GP20, board.GP22],
            clock_pin=board.GP11,
            latch_pin=board.GP12,
            output_enable_pin=board.GP13,
            tile=1,
            serpentine=serpentine,
            doublebuffer=doublebuffer,
        )

        self.display = framebufferio.FramebufferDisplay(matrix, auto_refresh=True)

    def show(self, group: displayio.Group) -> None:
        try:
            self.display.root_group = group
        except AttributeError:
            self.display.show(group)
