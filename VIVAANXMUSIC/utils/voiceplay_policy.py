def should_prompt_after_track(
    *,
    enabled: bool,
    call_active: bool,
    queue_empty: bool,
    track_finished: bool,
) -> bool:
    """Return whether Voice Play should open an idle listening round."""
    return bool(enabled and call_active and queue_empty and track_finished)
