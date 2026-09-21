"""Offline sandbox-to-prod release record. Never deploys, connects, or opens DBs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def revision(repo, ref):
    return git(repo, 'rev-parse', '--verify', ref + '^{commit}')


def digest(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def prepare(repo, baseline, candidate):
    baseline, candidate = revision(repo, baseline), revision(repo, candidate)
    changes = git(repo, 'diff', '--name-status', baseline, candidate).splitlines()
    return {'version': 1, 'production_baseline_sha': baseline, 'candidate_sha': candidate,
            'candidate_tree': git(repo, 'rev-parse', candidate + '^{tree}'),
            'changes': changes,
            'policy': {'copy_sandbox_database': False, 'copy_runtime_files': False,
                       'copy_environment_or_credentials': False, 'automatic_deploy': False},
            'required_review': ['Reconcile newer production fixes; review the complete diff.',
                                'Review migrations AND startup/init code for business mutations.',
                                'Preserve production templates unless separately approved.',
                                'Use production-specific settings and persistent storage.',
                                'Recheck baseline and backup immediately before deployment.']}


FIELDS = ('ci_run', 'sandbox_deployment', 'sandbox_acceptance', 'production_backup',
          'storage_backup', 'migration_first_run', 'migration_repeat_run',
          'business_fingerprints', 'integrity_foreign_keys', 'template_review',
          'startup_review', 'rollback_plan')


def template(plan):
    return {'plan_sha256': digest(plan), 'candidate_sha': plan['candidate_sha'],
            'production_baseline_sha': plan['production_baseline_sha'],
            'evidence': {key: {'passed': False, 'reference': ''} for key in FIELDS},
            'explicit_approval': {'approved': False, 'candidate_sha': '', 'reference': ''}}


def check(plan, evidence):
    blockers = []
    for key, value in [('plan_sha256', digest(plan)), ('candidate_sha', plan['candidate_sha']),
                       ('production_baseline_sha', plan['production_baseline_sha'])]:
        if evidence.get(key) != value:
            blockers.append('Mismatch: ' + key)
    for key in FIELDS:
        item = evidence.get('evidence', {}).get(key, {})
        if item.get('passed') is not True or not str(item.get('reference', '')).strip():
            blockers.append('Missing evidence: ' + key)
    approval = evidence.get('explicit_approval', {})
    if (approval.get('approved') is not True or approval.get('candidate_sha') != plan['candidate_sha']
            or not str(approval.get('reference', '')).strip()):
        blockers.append('Explicit approval for exact candidate SHA required')
    return {'record_complete': not blockers, 'blockers': blockers,
            'deployment_performed': False,
            'notice': 'Checks record completeness only, not authenticity of evidence. Independently verify evidence and live baseline before deployment.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--repo', type=Path, default=Path.cwd())
    p.add_argument('--production-baseline', required=True)
    p.add_argument('--candidate', required=True)
    p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('check')
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        plan = prepare(args.repo, args.production_baseline, args.candidate)
        args.out.mkdir(parents=True, exist_ok=False)
        for name, data in [('plan.json', plan), ('evidence.json', template(plan))]:
            with (args.out / name).open('x') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        print('Prepared review record only. No code, data or deployment transferred.')
    else:
        result = check(json.loads(args.plan.read_text()), json.loads(args.evidence.read_text()))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result['record_complete'] else 2)


if __name__ == '__main__':
    main()
