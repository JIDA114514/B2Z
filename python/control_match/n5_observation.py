"""Causal N5 observation model; no calibration or physical execution claim."""
from dataclasses import replace
from .control_engine import _LocalClock


class ObservationClock(_LocalClock):
    def __init__(self, config, registration):
        super().__init__(replace(config, history_size=8, min_rate_span_ms=4000))
        self.registration = registration
        self.state = 'acquiring'
        self.candidate = None
        self.progress = 0
        self.seen = {}
        self.transitions = []
        self.first_recovery_sample = None
        self.last_candidate_available = None
        self.models = []
        self.segment = 0
        self.last_update_sample = None

    def transition(self, state):
        if state != self.state:
            previous, self.state = self.state, state
            self.transitions.append(dict(previous=previous, state=state,
                                         local_sample=self.progress, **self.details()))

    def advance(self, sample):
        self.progress = sample
        if self.points and self.state in ('tracking', 'holdover', 'stale'):
            age = self.sender_ms(sample) - self.latest_ref_ms
            self.transition('stale' if age > 10000 else 'holdover' if age > 2000 else 'tracking')
        if (self.state == 'reacquiring' and self.last_candidate_available is not None and
                sample - self.last_candidate_available > 10 * self.config.sample_rate):
            self.candidate = None
            self.transition('stale')

    def invalidate(self):
        self.transition('timeline_unverified')

    def restart(self):
        """Explicit new segment only; never shift the historical sample axis."""
        self.segment += 1
        self.progress = 0
        self.points = {}
        self.models = []
        self.seen = {}
        self.candidate = None
        self.first_recovery_sample = self.last_candidate_available = None
        self.last_update_sample = None
        self.transition('acquiring')

    def uncertainty_ms(self, sender_ms):
        if self.state not in ('tracking', 'holdover'):
            return None
        return super().uncertainty_ms(sender_ms)

    def score(self, slot, start):
        # Availability may follow several later packet markers in one decoder block.
        eligible = [m for m in self.models if m['available_sample'] < start]
        result = dict(slot_index=slot, sample_start=start, available_sample=self.progress,
                      segment=self.segment, residual_ms=None, estimated_ms=None,
                      status='model_unavailable', reference_quality='uncalibrated')
        if self.state == 'timeline_unverified':
            result['status'] = 'timeline_unverified'
        elif eligible:
            m = eligible[-1]
            sample = start - self.marker_offset_samples
            ref = slot * self.registration['period_ms']
            result.update(m, status='scored', available_sample=self.progress,
                          model_available_sample=m['available_sample'],
                          residual_ms=(sample-m['intercept']-m['slope']*ref)/self.nominal_slope,
                          estimated_ms=(sample-m['intercept'])/m['slope'],
                          update_age_ms=ref-m['latest_ref_ms'])
        return result

    def observe(self, slot, ref_ms, packet_start_sample):
        if self.state == 'timeline_unverified':
            return 'timeline_unverified'
        if slot in self.registration['probes']:
            return 'probe_held_out'
        if slot not in self.registration['candidates'][self.config.side]:
            return 'not_training_candidate'
        if ref_ms != slot * self.registration['period_ms']:
            return 'reference_plan_mismatch'
        value = (ref_ms, packet_start_sample)
        if slot in self.seen:
            return 'clock_duplicate' if self.seen[slot] == value else 'conflicting_slot'
        if self.seen and slot < max(self.seen):
            return 'out_of_order_training'
        self.seen[slot] = value
        if self.state == 'stale':
            self.first_recovery_sample = self.progress
            self.candidate = None
            self.transition('reacquiring')
        if self.state in ('acquiring', 'reacquiring'):
            if (self.candidate is None or self.last_candidate_available is not None and
                    self.progress-self.last_candidate_available > 10*self.config.sample_rate):
                self.candidate = _LocalClock(self.config)
            status = self.candidate.observe(slot, ref_ms, packet_start_sample)
            if status != 'clock_updated':
                return status
            self.last_candidate_available = self.progress
            details = self.candidate.details()
            if len(self.candidate.points) < 8 or details['training_span_ms'] < 4000:
                return 'candidate_accumulating'
            for key in ('points', 'slope', 'intercept', 'residual_ms', 'rate_fitted'):
                setattr(self, key, getattr(self.candidate, key))
            self.version += 1
            self.candidate = None
            status = 'clock_updated'
        else:
            if self.latest_ref_ms is not None and ref_ms-self.latest_ref_ms < 1000:
                return 'update_interval_not_due'
            status = super().observe(slot, ref_ms, packet_start_sample)
        if status == 'clock_updated':
            self.last_update_sample = self.progress
            self.models.append(dict(available_sample=self.progress, model_version=self.version,
                                    slope=self.slope, intercept=self.intercept,
                                    training_slots=list(self.points), latest_ref_ms=self.latest_ref_ms,
                                    recovery_model=self.first_recovery_sample is not None))
            self.transition('tracking')
            self.advance(self.progress)
        return status

    def details(self):
        return dict(super().details(), observation_state=self.state, segment=self.segment,
                    training_slots=list(self.points), processing_sample=self.progress,
                    candidate_slots=list(self.candidate.points) if self.candidate else [],
                    first_recovery_sample=self.first_recovery_sample,
                    last_update_sample=self.last_update_sample,
                    update_age_ms=self.sender_ms(self.progress)-self.latest_ref_ms if self.points else None,
                    sample_delta=self.progress-self.predict_sample(self.latest_ref_ms) if self.points else None,
                    reference_quality='uncalibrated' if self.config.external_reference_bound_ms is None else 'supplied_bound')
