 const form = document.getElementById("booking-form");
const result = document.getElementById("booking-result");
const tourSelect = document.getElementById("tour");
const list = document.getElementById("request-list");
const storageStatus = document.getElementById("storage-status");
const clearButton = document.getElementById("clear-requests");
const STORAGE_KEY = "zeleni-pateki-requests-v3";
let tours = [];
let requests = [];

function showMessage(message, ok = false) {
  result.className = ok ? "result success" : "result error";
  result.textContent = message;
}

function loadRequests() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const data = raw === null ? [] : JSON.parse(raw);
    if (!Array.isArray(data) || !data.every(item =>
      item && typeof item.tourName === "string" &&
      typeof item.date === "string" &&
      Number.isInteger(item.people) && item.people > 0 &&
      Number.isFinite(item.total) && item.total >= 0
    )) throw new Error("Невалиден формат на запазените заявки.");
    requests = data;
    storageStatus.textContent = "Локалните заявки са заредени.";
  } catch (error) {
    requests = [];
    storageStatus.textContent = "Запазените данни не могат да се прочетат. " +
      "Използвайте бутона за изтриване, за да ги нулирате.";
    console.error(error);
  }
}

function renderRequests() {
  list.replaceChildren();
  if (requests.length === 0) {
    const item = document.createElement("li");
    item.textContent = "Все още няма учебни заявки.";
    list.append(item);
    return;
  }
  for (const request of requests) {
    const item = document.createElement("li");
    item.textContent = `${request.tourName} | ${request.date} | ` +
      `${request.people} участници | ${request.total.toFixed(2)} лв.`;
    list.append(item);
  }
}

async function loadTours() {
  try {
    const response = await fetch("/api/tours");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!Array.isArray(data) || data.length === 0 || !data.every(tour =>
      tour && typeof tour.id === "string" && tour.id.trim() &&
      typeof tour.name === "string" && tour.name.trim() &&
      Number.isFinite(tour.price) && tour.price >= 0
    ) || new Set(data.map(tour => tour.id)).size !== data.length) {
      throw new Error("Проверете имената, цените и уникалните id в JSON.");
    }
    tours = data;
    tourSelect.replaceChildren(new Option("-- Изберете --", ""));
    for (const tour of tours) {
      tourSelect.add(new Option(`${tour.name} — ${tour.price} лв.`, tour.id));
    }
    tourSelect.disabled = false;
  } catch (error) {
    showMessage("Офертите не са заредени. Проверете localhost и tours.json.");
    console.error(error);
  }
}


form.addEventListener("submit", async function (event) {
  event.preventDefault();

  if (!form.checkValidity()) {
    form.reportValidity();
    return;
  }

  const name = document.getElementById("name").value.trim();
  const email = document.getElementById("email").value.trim();
  const people = Number(document.getElementById("people").value);
  const date = document.getElementById("date").value;
  const tour = tours.find(item => item.id === tourSelect.value);

  const today = new Date();
  const localToday =
    `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  if (!name || !email || !tour || !Number.isInteger(people) ||
      people < 1 || people > 10 || !date || date < localToday) {
    showMessage("Проверете данните във формуляра.");
    return;
  }

  try {
    const response = await fetch("/booking", {
      method: "POST",
      body: new FormData(form)
    });

   if (!response.ok) {
  const message = await response.text();
  showMessage(`Грешка ${response.status}: ${message}`);
  console.error("Booking error:", response.status, message);
  return;
}

    showMessage("Заявката е записана успешно в базата данни.", true);
    form.reset();
    await loadTours();
  } catch (error) {
    showMessage("Грешка при записване. Проверете конзолата.");
    console.error(error);
  }
});

clearButton.addEventListener("click", function () {
  if (!window.confirm("Да изтрия всички учебни заявки от този браузър?")) return;
  try {
    localStorage.removeItem(STORAGE_KEY);
    requests = [];
    renderRequests();
    storageStatus.textContent = "Всички локални учебни заявки са изтрити.";
    result.textContent = "";
    result.className = "result";
  } catch (error) {
    storageStatus.textContent = "Браузърът не позволи изтриване.";
    console.error(error);
  }
});

loadRequests();
renderRequests();
loadTours();