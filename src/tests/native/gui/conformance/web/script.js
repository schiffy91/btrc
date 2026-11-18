// The directory bundle's page: it reports what it could and could not load.
async function report() {
  const answer = { script: true, data: null, missing: null };
  try {
    const found = await fetch("data.json");
    answer.data = (await found.json()).value;
  } catch (error) {
    answer.data = "failed";
  }
  try {
    const absent = await fetch("absent.json");
    answer.missing = absent.ok ? "served" : "refused";
  } catch (error) {
    answer.missing = "refused";
  }
  answer.background = getComputedStyle(document.body).backgroundColor;
  window.btrc.post(answer);
}
report();
