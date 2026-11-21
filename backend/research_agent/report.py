import json

from backend.research_agent.evidence import metric_value
from backend.storage.research import EvidenceReader


def research_report(repository: EvidenceReader, round_id: str, status: str | None = None) -> str:
    run = repository.run(round_id)
    lines = ['# 量化研究简报', f"研究编号：`{round_id}`", f"本轮状态：**{status if status is not None else run['state']}**",
             f"研究问题：{run['question']}", f"数据版本：{run['dataset_version']}"]
    if run['error_code']:
        lines.append(f"未完成原因：{run['error_code']}；继续节点：`{run['next_node']}`")
    for hypothesis in repository.hypotheses(round_id):
        hid = hypothesis['hypothesis_id']
        spec = json.loads(hypothesis['factor_spec_json'])
        lines += [f"## {hid} · {hypothesis['mechanism']}", f"假设状态：**{hypothesis['status']}**",
                  f"研究理由：{hypothesis['rationale']}", '冻结规格：',
                  '```json\n' + json.dumps(spec, ensure_ascii=False, indent=2) + '\n```', '### 实验证据']
        for experiment in repository.experiments(hid):
            lines.append(f"- `{experiment['experiment_id']}` · {experiment['action']} · {experiment['phase']} · "
                         f"{experiment['classification']} · {experiment['execution_status']}")
            if experiment['error_code']:
                lines.append(f"  执行错误：{experiment['error_code']}")
        results = repository.results(hid)
        for result in results:
            lines += [f"### 结果 `{result['result_id']}`", f"上一版本：{result['supersedes_result_id']}", f"研究初判：{result['proposed_verdict']}",
                      "探索路径：", *["- " + item for item in json.loads(result["exploration_path"]) ]]
            for claim in json.loads(result['claims_json']):
                values = []
                for reference in claim['references']:
                    experiment = repository.experiment(reference['experiment_id'])
                    value = metric_value(json.loads(experiment['result_json']), reference['metric_path'])
                    values.append(f"{value}（`{reference['experiment_id']}` `{reference['metric_path']}`）")
                lines.append('- ' + claim['label'] + '：' + '；'.join(values))
            review = repository.review(result['result_id'])
            if review is None:
                lines.append('独立评审：**待完成**；已有证据不代表已通过验证。')
            else:
                lines += [f"独立评审：`{review.review_id}` · **{review.suggested_verdict}**",
                          f"来源校验：{review.provenance_check}",
                          '评审意见（独立判断，数值以实验引用为准）：', review.statistical_assessment,
                          *['- ' + item for item in review.critiques + review.provenance_errors]]
            lines += ['限制与未解决解释：', result['attribution_detail'],
                      *['- ' + item for item in json.loads(result['caveats'])]]
        if hypothesis['evidence_summary']:
            lines += ['评审回应与补测记录：', '```json\n' + json.dumps(
                json.loads(hypothesis['evidence_summary']), ensure_ascii=False, indent=2) + '\n```']
    if run['context_json']:
        context = json.loads(run['context_json'])
        references = context['retrieved_message_ids'] + context['recent_message_ids']
        if references:
            lines += ['会话参考（仅用于理解问题，不作为研究证据）：' + ', '.join(references)]
    return '\n\n'.join(lines)
