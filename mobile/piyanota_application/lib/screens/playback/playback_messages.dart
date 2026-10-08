import '../../models/voice_part.dart';
import '../../state/playback_providers.dart';

/// Every user-facing string on Playback (PIYA-208), in plain words for
/// choir members (NFR-3). Errors never show a raw status code.
class PlaybackMessages {
  PlaybackMessages._();

  static String arrangedBy(String composer) => 'arr. by $composer';
  static const String selectVoices = 'Select voice/s to hear.';
  static const String keepOneVoice = 'Keep at least one voice selected.';
  static const String voiceUnavailable = 'not available for this score';
  static const String loading = 'Loading your score…';
  static const String back = 'Back';
  static const String download = 'Download audio';
  static const String retry = 'Try again';
  static const String backToLibrary = 'Back to library';

  // Transport (user decision 2026-10-09).
  static const String play = 'Play';
  static const String pause = 'Pause';
  static const String toStart = 'Go to the beginning';
  static const String toLastBar = 'Go to the last bar';
  static const String back5 = 'Back 5 seconds';
  static const String forward5 = 'Forward 5 seconds';
  static const String seek = 'Playback position';

  static const String voiceMixer = 'Voice Mixer';
  static const String speed = 'Speed';

  // Placeholder sheets until PIYA-209/210/211.
  static const String mixerSheetTitle = 'Voice Mixer';
  static const String speedSheetTitle = 'Playback Speed';
  static const String exportSheetTitle = 'Export Audio';
  static const String comingSoon = 'Coming soon';
  static const String close = 'Close';

  // Review banner (PIYA-103 `review.reviewNeeded`).
  static const String review =
      'Automatic transcription — some notes may be wrong. Listen critically.';
  static const String dismissReview = 'Dismiss';

  static const String noScoreImage =
      'The score image couldn\'t be shown, but you can still listen.';
  static String pageLabel(int page, int total) => 'Score page $page of $total';

  static String voiceChip(VoicePart voice) => voice.label;

  /// m:ss, or h:mm:ss for anything an hour or longer.
  static String time(Duration value) {
    final seconds = value.inSeconds;
    final hours = seconds ~/ Duration.secondsPerHour;
    final minutes = (seconds % Duration.secondsPerHour) ~/ 60;
    final rest = (seconds % 60).toString().padLeft(2, '0');
    if (hours > 0) {
      return '$hours:${minutes.toString().padLeft(2, '0')}:$rest';
    }
    return '$minutes:$rest';
  }

  static String errorHeading(PlaybackError error) => switch (error) {
    PlaybackError.notReady => 'Still converting',
    PlaybackError.notFound => 'Score not found',
    PlaybackError.network => 'You\'re offline',
    PlaybackError.server => 'Couldn\'t open this score',
    PlaybackError.audio => 'Couldn\'t play this score',
    PlaybackError.sessionExpired => 'Please log in again',
  };

  static String errorBody(PlaybackError error) => switch (error) {
    PlaybackError.notReady =>
      'This score is still being converted into audio. Try again in a '
          'minute or two.',
    PlaybackError.notFound =>
      'We couldn\'t find this score. It may have been deleted.',
    PlaybackError.network => 'Check your internet connection, then try again.',
    PlaybackError.server =>
      'Something went wrong on our side. Try again in a moment.',
    PlaybackError.audio =>
      'The audio for this score didn\'t load. Try again, and if it keeps '
          'happening, re-scan the score.',
    PlaybackError.sessionExpired => 'Your session has ended.',
  };
}
