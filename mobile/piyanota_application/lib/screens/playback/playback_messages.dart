import '../../models/score_result.dart';
import '../../models/voice_part.dart';
import '../../state/playback_providers.dart';

/// Every user-facing string on Playback (PIYA-208), in plain words for
/// choir members (NFR-3). Errors never show a raw status code.
class PlaybackMessages {
  PlaybackMessages._();

  static String arrangedBy(String arranger) => 'arr. by $arranger';
  static const String selectVoices = 'Select voice/s to hear.';
  static const String keepOneVoice = 'Keep at least one voice selected.';
  static const String voiceUnavailable = 'not available for this score';

  // Failed-voice alert (PIYA-208, user decision 2026-10-09).
  static String failedVoicesTitle(List<VoicePart> voices) =>
      '${_names(voices)} can’t be played';
  static String failedVoicesBody(List<VoicePart> voices, int remaining) {
    final which = voices.length == 1
        ? 'The ${voices.single.label} part of this score is'
        : 'The ${_names(voices)} parts of this score are';
    final rest = switch (remaining) {
      1 => 'The other voice will play.',
      _ => 'The other ${_count(remaining)} voices will play.',
    };
    return '$which corrupted and can’t be played at all. $rest Please try '
        'again later.';
  }

  static const String ok = 'OK';

  // Muted-measures alert (PIYA-207 AC10 / PIYA-208).
  static const String mutedTitle = 'Some measures will be silent';
  static const String mutedBody =
      'These measures were too damaged to play, so they will be silent. '
      'Everything else plays as normal.';
  static const String dontShowAgain = 'Don’t show again for this score';

  /// "Bass: m. 4", or "Bass: page 1, system 2" (counting from 1) when the
  /// measure couldn't be numbered.
  static String mutedLine(MutedMeasure measure) {
    final bar = measure.bar;
    if (bar != null) {
      return '${measure.voice.label}: ${bar == 0 ? 'pickup' : 'm. $bar'}';
    }
    final page = (measure.pageIndex ?? 0) + 1;
    final system = measure.systemIndex;
    return system == null
        ? '${measure.voice.label}: page $page'
        : '${measure.voice.label}: page $page, system ${system + 1}';
  }

  // Solo on a voice whose chip is off (PIYA-209, user decision 2026-10-09).
  static String soloChipOffTitle(VoicePart voice) =>
      '${voice.label} is turned off';
  static String soloChipOffBody(VoicePart voice) =>
      'You won’t hear ${voice.label} while its voice button on the '
      'Playback screen is off, even when it’s soloed.';
  static String turnOn(VoicePart voice) => 'Turn ${voice.label} on';
  static const String cancel = 'Cancel';

  static String _names(List<VoicePart> voices) {
    final labels = [for (final voice in voices) voice.label];
    if (labels.length < 3) return labels.join(' and ');
    return '${labels.sublist(0, labels.length - 1).join(', ')} and '
        '${labels.last}';
  }

  static String _count(int n) => switch (n) {
    2 => 'two',
    3 => 'three',
    _ => '$n',
  };
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

  /// The X on every Playback sheet.
  static const String close = 'Close';

  // Voice Mixer sheet (PIYA-209), wording from the mockup.
  static const String mixerTitle = 'Voice Mixer';
  static const String mixerSubtitle = 'Adjust volume per voice and metronome';
  static const String metronomeClick = 'Metronome Click';
  static const String mute = 'Mute';

  /// Screen-reader labels; the row's name is not repeated on screen.
  static String soloLabel(String row) => 'Solo $row';
  static String muteLabel(String row) => 'Mute $row';
  static String volumeLabel(String row) => '$row volume';
  static String volumeValue(double level) => '${(level * 100).round()}%';
  static String rowUnavailable(String row) => '$row audio unavailable';

  /// Both sheets, instead of [metronomeUnavailable], when the result came
  /// without a tempo (ScoreResult.tempoKnown).
  static const String metronomeNeedsTempo =
      'Metronome needs the score tempo, which this score doesn’t have. '
      'The voices still play.';

  /// Under the Mixer's metronome row while it is off: level, Mute and
  /// Solo wait until it is switched on, here or in Speed (same toggle).
  static const String metronomeOff =
      'Off. Switch it on to hear it and change its level.';

  /// The Mixer metronome row's on/off switch (user decision 2026-10-21).
  static const String metronomeSwitchLabel = 'Metronome Click on';
  static const String on = 'On';
  static const String off = 'Off';

  /// Shown on both sheets when the click track couldn't be made or played.
  static const String metronomeUnavailable =
      'The metronome click isn’t available right now. The voices still play.';

  // Speed sheet (PIYA-210), wording from the mockup.
  static const String speedTitle = 'Speed';
  static const String speedSubtitle = 'Adjust playback speed.';
  static const String metronomeHint =
      'Listen along with a click to stay on beat';
  static const String playbackSpeed = 'Playback Speed';

  /// Quarter-note BPM whatever the meter (user decision 2026-10-09).
  static String bpmValue(int bpm) => '♩ = $bpm';
  static String bpmSpoken(int bpm) => '$bpm beats per minute';

  // Review banner (PIYA-103 `review.reviewNeeded`).
  static const String review =
      'Automatic transcription — some notes may be wrong. Listen critically.';
  static const String dismissReview = 'Dismiss';

  static const String noScoreImage =
      'The score image couldn\'t be shown, but you can still listen.';
  static const String indicatorUnavailable =
      'Score position indicator unavailable';
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
      'The audio for this score didn\'t load or stopped playing. Try '
          'again, and if it keeps happening, re-scan the score.',
    PlaybackError.sessionExpired => 'Your session has ended.',
  };
}
