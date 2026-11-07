"""Build RAM-only RouterOS tests from the actual native snapshot helpers."""
from pathlib import Path


def test_source(root):
    root = Path(root)
    source = (root / 'native/sdwan-controller.rsc').read_text()
    markers = ['    :local indexManaged do={\n', '    :local policyRoutes ',
               '    :local requireManaged do={\n', '    :local defaultAdmissionClosed false\n']
    if any(source.count(marker) != 1 for marker in markers):
        raise ValueError('Native snapshot helper boundaries changed; review the test builder')
    a, b, c, d = [source.index(marker) for marker in markers]
    if not a < b < c < d:
        raise ValueError('Native snapshot helper order changed')
    helpers = source[a:b] + source[c:d]
    cases = (root / 'tests/native_policy_snapshot_cases.rsc').read_text()
    return (':global sdwanSnapshotSelfTestJSON\n:local checks [:toarray ""]\n'
            ':onerror testFailure in={\n' + helpers + cases + '\n'
            ':set sdwanSnapshotSelfTestJSON [:serialize to=json value={"pass"=true;"checks"=$checks} options=json.no-string-conversion]\n'
            '} do={ :set sdwanSnapshotSelfTestJSON [:serialize to=json value={"pass"=false;"checks"=$checks;"error"=$testFailure} options=json.no-string-conversion] }\n')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(test_source(args.source))
