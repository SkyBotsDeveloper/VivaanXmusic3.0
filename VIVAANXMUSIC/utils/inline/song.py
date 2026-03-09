from VIVAANXMUSIC.utils.button_styles import danger_button, primary_button, success_button


def song_markup(_, vidid):
    buttons = [
        [
            success_button(
                text=_["SG_B_2"],
                callback_data=f"song_helper audio|{vidid}",
            ),
            primary_button(
                text=_["SG_B_3"],
                callback_data=f"song_helper video|{vidid}",
            ),
        ],
        [
            danger_button(
                text=_["CLOSE_BUTTON"], callback_data="close"
            ),
        ],
    ]
    return buttons
