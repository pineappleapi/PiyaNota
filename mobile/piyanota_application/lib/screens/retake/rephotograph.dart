import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../models/score_details.dart';
import '../../models/voice_part.dart';
import '../../routes/app_routes.dart';
import '../../state/processing_providers.dart';

/// The whole-score Re-photograph flow (PIYA-207 AC11/AC12, PIYA-208,
/// PIYA-209, PIYA-218 AC3): the post-processing offer, the unreadable-voice
/// alert, the once-per-job flag and the hand-off to Capture. Shared by
/// Processing, the library, Playback and the Mixer so they say the same
/// thing.
class RephotographMessages {
  RephotographMessages._();

  static const String rephotograph = 'Re-photograph';
  static const String cancel = 'Cancel';

  /// AC11 wording, e.g. "The Tenor part couldn't be read from these
  /// photos".
  static String offerTitle(List<VoicePart> voices) => voices.length == 1
      ? 'The ${voices.single.label} part couldn\'t be read from these photos'
      : 'The ${_names(voices)} parts couldn\'t be read from these photos';

  static const String offerBody =
      'Re-photographing the whole score may fix it. You can also listen to '
      'the voices that were read.';

  /// AC11: N = 4 − number of failed voices.
  static String continueWith(int playable) => playable == 1
      ? 'Continue with 1 voice'
      : 'Continue with $playable voices';

  /// PIYA-208 / PIYA-209 chip and Mixer-row alert.
  static String unreadableTitle(VoicePart voice) =>
      '${voice.label} couldn\'t be read from the photos';

  static const String unreadableBody =
      'Re-photographing the whole score may fix it.';

  static String _names(List<VoicePart> voices) {
    final labels = [for (final voice in voices) voice.label];
    if (labels.length < 3) return labels.join(' and ');
    return '${labels.sublist(0, labels.length - 1).join(', ')} and '
        '${labels.last}';
  }
}

/// What the AC11 offer was answered with.
enum RephotographChoice { rephotograph, continuePlayback }

/// The AC11 offer for [voices] (the `unreadable` ones, SATB order).
/// [playable] is N in "Continue with N voices". Null when system Back
/// dismissed it: the caller then goes to the library without opening
/// Playback, and the offer is not marked answered.
Future<RephotographChoice?> showRephotographOffer(
  BuildContext context, {
  required List<VoicePart> voices,
  required int playable,
}) => showDialog<RephotographChoice>(
  context: context,
  // Only the two buttons or Back answer it; a stray tap outside must not.
  barrierDismissible: false,
  builder: (context) => AlertDialog(
    key: const ValueKey('rephotograph-offer'),
    title: Text(RephotographMessages.offerTitle(voices)),
    content: const Text(RephotographMessages.offerBody),
    actions: [
      TextButton(
        onPressed: () =>
            Navigator.of(context).pop(RephotographChoice.continuePlayback),
        child: Text(RephotographMessages.continueWith(playable)),
      ),
      TextButton(
        onPressed: () =>
            Navigator.of(context).pop(RephotographChoice.rephotograph),
        child: const Text(RephotographMessages.rephotograph),
      ),
    ],
  ),
);

/// "`<Voice>` couldn't be read from the photos" (PIYA-208 chip, PIYA-209
/// Mixer row). True for Re-photograph; false for Cancel or a dismiss.
Future<bool> showUnreadableVoiceAlert(
  BuildContext context, {
  required VoicePart voice,
}) async {
  final retake = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      key: const ValueKey('unreadable-voice-alert'),
      title: Text(RephotographMessages.unreadableTitle(voice)),
      content: const Text(RephotographMessages.unreadableBody),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: const Text(RephotographMessages.cancel),
        ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(true),
          child: const Text(RephotographMessages.rephotograph),
        ),
      ],
    ),
  );
  return retake ?? false;
}

/// AC11 "stays once per job": answered offers, per `jobId` on the device
/// (AC12: a retake is a new job, so its own unreadable voices are offered
/// again). A storage failure reads as "not answered" and a failed save is
/// only logged: at worst the offer shows again, never a crash.
class RephotographOfferPrefs {
  const RephotographOfferPrefs._();

  @visibleForTesting
  static String keyFor(String jobId) => 'rephotograph_offer_answered_$jobId';

  static Future<bool> isAnswered(String jobId) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      return prefs.getBool(keyFor(jobId)) ?? false;
    } on Object catch (e) {
      debugPrint('Re-photograph offer preference unread: $e');
      return false;
    }
  }

  static Future<void> markAnswered(String jobId) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(keyFor(jobId), true);
    } on Object catch (e) {
      debugPrint('Re-photograph offer preference not saved: $e');
    }
  }
}

/// Opens Capture for a whole-score retake of [jobId] (PIYA-207 AC12):
/// no pages, step 1 pre-filled with the old job's details. [details] is
/// used when the caller already has them from a PIYA-102 answer;
/// otherwise one PIYA-102 call on [jobId] fetches them, and if that
/// fails the form starts with just [title] (still editable). Capture sits
/// on top of the library, so leaving it changes nothing and lands there.
/// [retakeOfScoreId] is the completed score the retake fills.
Future<void> startWholeRetake(
  BuildContext context,
  WidgetRef ref, {
  required String jobId,
  required String title,
  ScoreDetails? details,
  int? retakeOfScoreId,
}) async {
  final navigator = Navigator.of(context);
  var prefill = details;
  if (prefill == null) {
    try {
      final status = await ref.read(processingApiProvider).fetchStatus(jobId);
      prefill = status.details;
    } on Object catch (e) {
      // The retake still works; only the pre-fill is lost.
      debugPrint('Re-photograph: details not fetched for $jobId: $e');
    }
  }
  if (!navigator.mounted) return;
  await navigator.pushNamedAndRemoveUntil(
    AppRoutes.capture,
    (route) => route.settings.name == AppRoutes.scoreLibrary || route.isFirst,
    arguments: WholeRetakeArguments(
      replacesJobId: jobId,
      details: prefill ?? ScoreDetails(title: title),
      retakeOfScoreId: retakeOfScoreId,
    ),
  );
}
