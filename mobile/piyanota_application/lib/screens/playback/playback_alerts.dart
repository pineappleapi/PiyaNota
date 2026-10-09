import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../models/score_result.dart';
import '../../models/voice_part.dart';
import 'playback_messages.dart';

/// The system alerts Playback shows (user decisions 2026-10-09): a voice
/// that can't play at all, measures that will be silent, and a Solo that
/// can't be heard. AlertDialogs like the rest of the app's confirmations.

/// "Wholly corrupted, the others will play" for [voices] (in SATB order);
/// [remaining] is how many voices are left to play.
Future<void> showFailedVoicesAlert(
  BuildContext context, {
  required List<VoicePart> voices,
  required int remaining,
}) => showDialog<void>(
  context: context,
  builder: (context) => AlertDialog(
    key: const ValueKey('failed-voices-alert'),
    title: Text(PlaybackMessages.failedVoicesTitle(voices)),
    content: Text(PlaybackMessages.failedVoicesBody(voices, remaining)),
    actions: [
      TextButton(
        onPressed: () => Navigator.of(context).pop(),
        child: const Text(PlaybackMessages.ok),
      ),
    ],
  ),
);

/// Lists [measures] (PIYA-207 AC10). True when "Don't show again for this
/// score" was ticked when it was closed.
Future<bool> showMutedMeasuresAlert(
  BuildContext context, {
  required List<MutedMeasure> measures,
}) async {
  final lines = <String>{
    for (final measure in measures) PlaybackMessages.mutedLine(measure),
  };
  var hide = false;
  await showDialog<void>(
    context: context,
    builder: (context) => StatefulBuilder(
      builder: (context, setState) => AlertDialog(
        key: const ValueKey('muted-measures-alert'),
        title: const Text(PlaybackMessages.mutedTitle),
        scrollable: true,
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(PlaybackMessages.mutedBody),
            const SizedBox(height: 12),
            for (final line in lines)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(
                  line,
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
              ),
            const SizedBox(height: 4),
            CheckboxListTile(
              key: const ValueKey('muted-dont-show-again'),
              value: hide,
              onChanged: (value) => setState(() => hide = value ?? false),
              title: const Text(PlaybackMessages.dontShowAgain),
              controlAffinity: ListTileControlAffinity.leading,
              contentPadding: EdgeInsets.zero,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text(PlaybackMessages.ok),
          ),
        ],
      ),
    ),
  );
  return hide;
}

/// Solo was ticked on [voice] while its chip is off. True for "Turn
/// `<Voice>` on", false for Cancel or a dismiss.
Future<bool> showSoloChipOffAlert(
  BuildContext context, {
  required VoicePart voice,
}) async {
  final turnOn = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      key: const ValueKey('solo-chip-off-alert'),
      title: Text(PlaybackMessages.soloChipOffTitle(voice)),
      content: Text(PlaybackMessages.soloChipOffBody(voice)),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: const Text(PlaybackMessages.cancel),
        ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(true),
          child: Text(PlaybackMessages.turnOn(voice)),
        ),
      ],
    ),
  );
  return turnOn ?? false;
}

/// "Don't show again for this score", per `scoreId` on the device. A
/// storage failure reads as "not hidden" and a failed save is only
/// logged: at worst the alert shows again, never a crash.
class MutedAlertPrefs {
  const MutedAlertPrefs._();

  @visibleForTesting
  static String keyFor(int scoreId) => 'muted_alert_hidden_$scoreId';

  static Future<bool> isHidden(int scoreId) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      return prefs.getBool(keyFor(scoreId)) ?? false;
    } on Object catch (e) {
      debugPrint('Playback: muted-alert preference unread: $e');
      return false;
    }
  }

  static Future<void> hide(int scoreId) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(keyFor(scoreId), true);
    } on Object catch (e) {
      debugPrint('Playback: muted-alert preference not saved: $e');
    }
  }
}
