import json
import math

from backend.research_agent.schemas import Claim, CorrectionMetrics, ExperimentOutput, HypothesisSpec, MultipleTestingInput
from backend.storage.research import EvidenceReader


def metric_value(result: dict, path: str) -> int | float:
    value = result
    for token in path.split('/')[1:]:
        key = token.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if isinstance(value, list) else value[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'Metric path must resolve to a finite number: {path}')
    return value


def numerical_paths(value, prefix='/metrics'):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from numerical_paths(child, prefix + '/' + key.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from numerical_paths(child, prefix + '/' + str(index))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield prefix


def verify_evidence(reader: EvidenceReader, result_id: str, hypothesis_id: str) -> list[str]:
    result = reader.result(result_id)
    errors = []
    if result['hypothesis_id'] != hypothesis_id:
        return ['Requested hypothesis does not own this result']
    hypothesis = reader.hypothesis(hypothesis_id, result['spec_version'])
    run = reader.run(hypothesis['round_id'])
    spec = HypothesisSpec.model_validate_json(hypothesis['factor_spec_json'])
    family = reader.hypotheses(hypothesis['round_id'])
    family_ids = {h['hypothesis_id'] for h in family if h['spec_version'] == 1}
    histories = {h: reader.experiments(h) for h in family_ids}
    all_experiments = {e['experiment_id']: e for history in histories.values() for e in history}
    evidence_ids = json.loads(result['evidence_experiment_ids'])
    own_ids = {e['experiment_id'] for e in histories[hypothesis_id]}
    if not own_ids.issubset(evidence_ids):
        errors.append('Result omits experiments from the hypothesis history')
    if json.loads(run['manifest_json'])['evidence_kind'] != 'empirical':
        errors.append('Dataset is not empirical')
    check_ids = set(evidence_ids) | {e['experiment_id'] for e in all_experiments.values()
                                     if e['phase'] in ('primary', 'correction')}
    for experiment_id in check_ids:
        if experiment_id not in all_experiments:
            errors.append(f'Missing or unrelated experiment: {experiment_id}')
            continue
        experiment = all_experiments[experiment_id]
        if experiment['dataset_version'] != run['dataset_version']:
            errors.append(f'Dataset version mismatch: {experiment_id}')
        if experiment['hypothesis_id'] == hypothesis_id and experiment['spec_version'] != result['spec_version']:
            errors.append(f'Specification version mismatch: {experiment_id}')
        if experiment['phase'] == 'primary' and experiment['classification'] != 'registered':
            errors.append(f'Primary evidence is exploratory: {experiment_id}')
        if experiment['execution_status'] != 'success':
            # Recorded failures are visible. A later successful attempt with the same key resolves execution failure.
            resolved = any(e['run_key'] == experiment['run_key'] and e['execution_status'] == 'success'
                           for e in all_experiments.values())
            if not resolved:
                errors.append(f'Experiment has no successful evidence: {experiment_id}')
            continue
        output = ExperimentOutput.model_validate_json(experiment['result_json'])
        if (output.dataset_version != experiment['dataset_version'] or output.spec_version != experiment['spec_version']
                or output.engine_version != experiment['engine_version']):
            errors.append(f'Output provenance mismatch: {experiment_id}')
        if output.evidence_kind != 'empirical':
            errors.append(f'Synthetic evidence: {experiment_id}')
    for member in family_ids:
        for action in ('evaluate_factor', 'walk_forward'):
            if not any(e['phase'] == 'primary' and e['action'] == action and e['execution_status'] == 'success'
                       for e in histories[member]):
                errors.append(f'Missing primary evidence: {member}/{action}')
    corrections = [e for e in all_experiments.values() if e['phase'] == 'correction' and e['execution_status'] == 'success']
    if len(corrections) != 1:
        errors.append('A complete registered-family correction is required')
    else:
        correction = corrections[0]
        metrics = CorrectionMetrics.model_validate(json.loads(correction['result_json'])['metrics'])
        if set(metrics.hypothesis_ids) != family_ids or set(metrics.adjusted_p_values) != family_ids or metrics.omissions:
            errors.append('Multiple-testing correction omits registered hypotheses')
        if any(value is None or not 0 <= value <= 1 for value in metrics.adjusted_p_values.values()):
            errors.append('Multiple-testing correction has missing or invalid adjusted p-values')
        if correction['experiment_id'] not in evidence_ids:
            errors.append('Result does not reference its correction evidence')
        parameters = MultipleTestingInput.model_validate_json(correction['params_json'])
        if {member.hypothesis_id for member in parameters.members} != family_ids:
            errors.append('Correction inputs omit registered family members')
        if parameters.alpha != run['significance_level']:
            errors.append('Correction significance level differs from registration')
        for item in parameters.members:
            member = item.model_dump()
            try:
                recorded = all_experiments[member['experiment_id']]
                registered = HypothesisSpec.model_validate_json(reader.hypothesis(member['hypothesis_id'])['factor_spec_json'])
                if (recorded['hypothesis_id'] != member['hypothesis_id'] or recorded['phase'] != 'primary'
                        or recorded['action'] != 'evaluate_factor' or recorded['execution_status'] != member['execution_status']
                        or member['metric_path'] != registered.primary_p_value):
                    errors.append('Correction references a different primary hypothesis or metric')
                value = metric_value(json.loads(recorded['result_json']), member['metric_path'])
                if value != member['p_value']:
                    errors.append('Correction input disagrees with recorded primary p-value')
            except (KeyError, TypeError, ValueError, IndexError):
                errors.append('Correction primary metric reference cannot be resolved')
    for raw in json.loads(result['claims_json']):
        claim = Claim.model_validate(raw)
        for ref in claim.references:
            try:
                if ref.experiment_id not in evidence_ids:
                    raise ValueError('Claim is not in the submitted evidence')
                experiment = all_experiments[ref.experiment_id]
                if experiment['execution_status'] != 'success':
                    raise ValueError('Claim references an unsuccessful experiment')
                metric_value(json.loads(experiment['result_json']), ref.metric_path)
            except (KeyError, ValueError, TypeError, IndexError) as exc:
                errors.append(f'Unsupported claim {claim.label}: {exc}')
    primary = [e for e in histories[hypothesis_id] if e['action'] == 'evaluate_factor' and e['phase'] == 'primary'
               and e['execution_status'] == 'success']
    for experiment in primary:
        try:
            metric_value(json.loads(experiment['result_json']), spec.primary_metric)
            metric_value(json.loads(experiment['result_json']), spec.primary_p_value)
        except (KeyError, ValueError, TypeError, IndexError):
            errors.append('Registered primary metric or p-value is missing')
    return errors
