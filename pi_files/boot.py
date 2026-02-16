import storage

deploy_mode = True
try:
    import board
    import digitalio

    # Hold Button 2 (GP15) at boot to keep USB storage enabled for deploys.
    deploy_button = digitalio.DigitalInOut(board.GP15)
    deploy_button.switch_to_input(pull=digitalio.Pull.UP)
    deploy_mode = not deploy_button.value
    deploy_button.deinit()
except Exception:
    # If we can't read the pin, keep USB enabled to avoid lockout.
    deploy_mode = True

if not deploy_mode:
    try:
        storage.disable_usb_drive()
        storage.remount("/", readonly=False)
    except Exception:
        pass
