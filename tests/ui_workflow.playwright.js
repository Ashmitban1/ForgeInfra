// Run with the Playwright MCP browser_run_code_unsafe filename option.
// Requires a FRESH tests/ui_backend.py server on port 8002 and Vite on 5173.
// Run in an isolated browser context; all API traffic is forwarded to test-only providers/storage.
async (page) => {
  await page.unroute('http://127.0.0.1:8000/**');
  await page.route('http://127.0.0.1:8000/**', route => route.continue({
    url: route.request().url().replace('127.0.0.1:8000', '127.0.0.1:8002'),
  }));
  const refreshSample = async fault => page.evaluate(async fault => {
    const c = await (await fetch('http://127.0.0.1:8000/api/incidents/INC-COOLING-001')).json();
    const response = await fetch('http://127.0.0.1:8000/api/telemetry', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device_id: c.device_id,
        ...c.hardware, cooling_fault: fault, observed_at: new Date().toISOString(), sequence: c.hardware.sequence + 1 }) });
    if (!response.ok) throw Error(await response.text());
    return response.json();
  }, fault);
  const enableCredential = async () => {
    await page.getByLabel('Reviewer credential', { exact: true }).fill('unit-test-only-alice-credential-000000000000');
    await page.getByRole('button', { name: 'Inspect approval package', exact: true }).click();
  };
  const enabled = async label => page.waitForFunction(label => {
    const button = [...document.querySelectorAll('button')].find(item => item.textContent === label);
    return button && !button.disabled;
  }, label);
  await page.goto('http://127.0.0.1:5173/#/engineering/INC-COOLING-001');
  await refreshSample(true);
  await enabled('Run investigation');
  await page.getByRole('button', { name: 'Run investigation', exact: true }).click();
  await page.getByText('VERIFIED', { exact: true }).waitFor({ timeout: 20000 });
  if (!(await page.locator('.actual-diff').innerText()).includes('cooling_fault')) throw Error('Actual candidate diff missing');
  await enabled('Request Gemini review');
  await page.getByRole('button', { name: 'Request Gemini review', exact: true }).click();
  await page.getByRole('region', { name: 'Gemini recommendation', exact: true }).getByText('REQUEST_REPAIR_REVIEW', { exact: true }).first().waitFor();
  await enableCredential();
  await enabled('Approve inspected candidate');
  await page.getByRole('button', { name: 'Approve inspected candidate', exact: true }).click();
  await page.getByRole('region', { name: 'Approval', exact: true }).getByText('APPROVED', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Create Jira Issue & Notify Slack', exact: true }).click();
  await page.getByText(/^Slack: DELIVERED/).waitFor();
  const first = await page.evaluate(async () => (await fetch('http://127.0.0.1:8000/__test__/stats')).json());
  if (first.jira !== 1 || first.slack !== 1 || first.decisions !== 1 || first.nvidia_clients !== 1) throw Error('Duplicate effects: ' + JSON.stringify(first));
  await refreshSample(true);
  await page.reload();
  await page.getByRole('region', { name: 'Approval', exact: true }).getByText('APPROVED', { exact: true }).waitFor();
  if (await page.getByLabel('Reviewer credential', { exact: true }).inputValue()) throw Error('Credential persisted after reload');
  await page.getByRole('link', { name: 'Mission Control', exact: true }).click();
  await page.getByRole('img', { name: /Stored and current temperature readings/ }).first().waitFor();
  await refreshSample(false);
  await page.goto('http://127.0.0.1:5173/#/engineering/INC-COOLING-001');
  await page.getByRole('region', { name: 'Approval', exact: true }).getByText('STALE', { exact: true }).waitFor();
  if (!await page.getByRole('button', { name: 'Approve inspected candidate', exact: true }).isDisabled()) throw Error('Stale approval enabled');
  await refreshSample(true);
  await page.getByRole('button', { name: 'Run new investigation / Retry', exact: true }).click();
  await page.waitForFunction(async () => (await (await fetch('http://127.0.0.1:8000/__test__/stats')).json()).nvidia_clients === 2);
  await enableCredential();
  await enabled('Reject inspected candidate');
  await page.getByRole('button', { name: 'Reject inspected candidate', exact: true }).click();
  await page.getByRole('region', { name: 'Approval', exact: true }).getByText('REJECTED', { exact: true }).waitFor();
  await page.evaluate(() => fetch('http://127.0.0.1:8000/__test__/monitor-failure', { method: 'POST' }));
  const failed = await refreshSample(true);
  if (failed.legacy_monitor.status !== 'UNKNOWN' || failed.reliability.mismatch !== null || !failed.should_alert) throw Error('Monitor failure suppressed independent alert');
  await page.getByRole('link', { name: 'Mission Control', exact: true }).click();
  await page.getByText(/Comparison unavailable: the legacy monitor has no verified decision/).waitFor();
  return { investigation: 'PASS', actualDiff: 'PASS', review: 'PASS', approval: 'PASS', rejection: 'PASS',
    notificationIdempotency: first, persistedChart: 'PASS', credentialCleared: 'PASS', staleApprovalBlocked: 'PASS', unknownMonitorAlert: 'PASS' };
}
