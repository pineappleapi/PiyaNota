import 'dart:async';

import 'package:flutter/material.dart';

import '../../../models/score_details.dart';
import '../../../theme/app_theme.dart';
import '../settings_messages.dart';

/// PIYA-212 AC8: − [♩ = 90] +, clamped to 30–240. Holding a button keeps
/// stepping, so 90 → 200 is one press rather than 110 taps. Exposed to
/// screen readers as one adjustable value (swipe up/down), not two
/// unrelated buttons.
///
/// [onChanged] fires on every step so the value on screen tracks the
/// finger; [onCommit] fires once per gesture (each tap, or a hold when it
/// ends) so the parent saves once instead of every 90 ms.
class TempoStepper extends StatefulWidget {
  const TempoStepper({
    super.key,
    required this.value,
    required this.onChanged,
    required this.onCommit,
  });

  final int value;
  final ValueChanged<int> onChanged;
  final ValueChanged<int> onCommit;

  static const int min = ScoreDetails.minTempo;
  static const int max = ScoreDetails.maxTempo;

  @override
  State<TempoStepper> createState() => _TempoStepperState();
}

class _TempoStepperState extends State<TempoStepper> {
  static const Duration _repeatEvery = Duration(milliseconds: 90);
  static const double _valueFontSize = 24;

  Timer? _repeat;

  /// The value as of the last step, so a held button keeps counting even
  /// before the parent has rebuilt with the previous step.
  late int _current = widget.value;

  /// The value when the current hold began; null when no hold is active.
  /// Outlives [_repeat], which stops early at the clamp while the finger
  /// is still down.
  int? _holdStart;

  @override
  void didUpdateWidget(TempoStepper oldWidget) {
    super.didUpdateWidget(oldWidget);
    // Outside a hold the parent is the truth, including a rollback after a
    // failed save.
    if (_holdStart == null) _current = widget.value;
  }

  @override
  void dispose() {
    _repeat?.cancel();
    // Leaving the screen mid-hold must not lose the steps already shown.
    if (_holdStart != null && _holdStart != _current) {
      widget.onCommit(_current);
    }
    super.dispose();
  }

  /// One step; false when already at the clamp.
  bool _advance(int delta) {
    final next = (_current + delta).clamp(TempoStepper.min, TempoStepper.max);
    if (next == _current) {
      _repeat?.cancel();
      _repeat = null;
      return false;
    }
    _current = next;
    widget.onChanged(next);
    return true;
  }

  void _tapStep(int delta) {
    if (_advance(delta)) widget.onCommit(_current);
  }

  /// A long press wins the gesture arena over the tap, so the tap's own
  /// step never fires; the hold makes the first step itself.
  void _startHold(int delta) {
    _repeat?.cancel();
    _holdStart = _current;
    _advance(delta);
    _repeat = Timer.periodic(_repeatEvery, (_) => _advance(delta));
  }

  void _endHold() {
    _repeat?.cancel();
    _repeat = null;
    final start = _holdStart;
    _holdStart = null;
    if (start != null && start != _current) widget.onCommit(_current);
  }

  @override
  Widget build(BuildContext context) {
    final value = widget.value;
    final canSlow = value > TempoStepper.min;
    final canSpeed = value < TempoStepper.max;

    return Semantics(
      container: true,
      label: SettingsMessages.defaultTempo,
      value: SettingsMessages.tempoSemanticsValue(value),
      increasedValue: canSpeed
          ? SettingsMessages.tempoSemanticsValue(value + 1)
          : null,
      decreasedValue: canSlow
          ? SettingsMessages.tempoSemanticsValue(value - 1)
          : null,
      onIncrease: canSpeed ? () => _tapStep(1) : null,
      onDecrease: canSlow ? () => _tapStep(-1) : null,
      child: Row(
        children: [
          _StepButton(
            icon: Icons.remove_rounded,
            tooltip: SettingsMessages.slower,
            enabled: canSlow,
            onTap: () => _tapStep(-1),
            onHoldStart: () => _startHold(-1),
            onHoldEnd: _endHold,
          ),
          Expanded(
            child: ExcludeSemantics(
              child: FittedBox(
                // At 2x text on a 320 dp phone the value shrinks to fit
                // between the buttons instead of overflowing them.
                fit: BoxFit.scaleDown,
                child: Text(
                  SettingsMessages.tempoValue(value),
                  key: const ValueKey('settings-tempo-value'),
                  maxLines: 1,
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    fontSize: _valueFontSize,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.settingsText,
                    fontFeatures: const [FontFeature.tabularFigures()],
                  ),
                ),
              ),
            ),
          ),
          _StepButton(
            icon: Icons.add_rounded,
            tooltip: SettingsMessages.faster,
            enabled: canSpeed,
            onTap: () => _tapStep(1),
            onHoldStart: () => _startHold(1),
            onHoldEnd: _endHold,
          ),
        ],
      ),
    );
  }
}

class _StepButton extends StatelessWidget {
  const _StepButton({
    required this.icon,
    required this.tooltip,
    required this.enabled,
    required this.onTap,
    required this.onHoldStart,
    required this.onHoldEnd,
  });

  final IconData icon;
  final String tooltip;
  final bool enabled;
  final VoidCallback onTap;
  final VoidCallback onHoldStart;
  final VoidCallback onHoldEnd;

  static const double _size = kMinInteractiveDimension;
  static const double _iconSize = 24;
  static const double _disabledAlpha = 0.35;

  @override
  Widget build(BuildContext context) {
    final fill = enabled
        ? AppTheme.settingsStepperFill
        : AppTheme.settingsStepperFill.withValues(alpha: _disabledAlpha);
    // The parent Semantics carries increase/decrease; these stay out of
    // the tree so TalkBack doesn't read three controls for one value.
    return ExcludeSemantics(
      child: Tooltip(
        message: tooltip,
        child: GestureDetector(
          onLongPressStart: enabled ? (_) => onHoldStart() : null,
          // Never gated on [enabled]: a hold that reaches the clamp
          // disables this button mid-gesture, and the release must still
          // arrive or the hold is never saved.
          onLongPressEnd: (_) => onHoldEnd(),
          onLongPressCancel: onHoldEnd,
          child: Material(
            color: fill,
            shape: const CircleBorder(),
            clipBehavior: Clip.antiAlias,
            child: InkWell(
              onTap: enabled ? onTap : null,
              highlightColor: AppTheme.darken(AppTheme.settingsStepperFill),
              child: SizedBox.square(
                dimension: _size,
                child: Icon(icon, size: _iconSize, color: Colors.white),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
