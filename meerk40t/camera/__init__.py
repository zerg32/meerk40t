name = "camera"


def composite_bed_photo_on_device_dc(scene, dc):
    """Draw the camera bed image when the optional camera stack is available."""
    try:
        from .camera import composite_bed_photo_on_device_dc as composite
    except ImportError:
        return
    composite(scene, dc)
