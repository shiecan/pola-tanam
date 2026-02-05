const info = document.getElementById("lokasi-info");
const lokasiInput = document.getElementById("lokasi");
const alamatInput = document.getElementById("alamat_lengkap");
const latInput = document.getElementById("lat");
const lonInput = document.getElementById("lon");
const cariBtn = document.getElementById("cari-alamat");

function setInfo(message, isError = false) {
  if (!info) return;
  info.textContent = message;
  info.classList.toggle("warn", isError);
}

async function cariAlamat() {
  const apiKey = window.GEOAPIFY_KEY;
  if (!apiKey || apiKey === "YOUR_GEOAPIFY_KEY") {
    setInfo("API key Geoapify belum diatur.", true);
    return;
  }

  const query = (lokasiInput?.value || "").trim();
  if (!query) {
    setInfo("Masukkan lokasi terlebih dahulu.", true);
    return;
  }

  setInfo("Mencari alamat...");
  const url = new URL("https://api.geoapify.com/v1/geocode/search");
  url.searchParams.set("text", query);
  url.searchParams.set("format", "json");
  url.searchParams.set("lang", "id");
  url.searchParams.set("limit", "1");
  url.searchParams.set("apiKey", apiKey);

  try {
    const response = await fetch(url.toString());
    if (!response.ok) {
      setInfo("Gagal mengambil alamat dari API.", true);
      return;
    }
    const data = await response.json();
    if (!data.results || data.results.length === 0) {
      setInfo("Alamat tidak ditemukan. Coba kata kunci lain.", true);
      return;
    }
    const result = data.results[0];
    alamatInput.value = result.formatted || "";
    latInput.value = result.lat ?? "";
    lonInput.value = result.lon ?? "";
    setInfo("Alamat berhasil diisi.");
  } catch (error) {
    setInfo("Terjadi error saat memanggil API.", true);
  }
}

if (cariBtn) {
  cariBtn.addEventListener("click", cariAlamat);
}

const timeline = document.getElementById("timeline");
const exportArea = document.getElementById("export-area");
const exportImageBtn = document.getElementById("export-image");
const exportPdfBtn = document.getElementById("export-pdf");

async function exportTimelineImage() {
  if (!exportArea || !window.html2canvas) return;
  exportArea.classList.add("exporting");
  await waitForImages(exportArea);
  await waitForLayout();
  const canvas = await window.html2canvas(exportArea, {
    backgroundColor: "#ffffff",
    scale: 2.5,
    useCORS: true,
    allowTaint: true,
  });
  exportArea.classList.remove("exporting");
  const link = document.createElement("a");
  link.download = "timeline-pola-tanam.png";
  link.href = canvas.toDataURL("image/png");
  link.click();
}

async function exportTimelinePdf() {
  if (!exportArea || !window.html2canvas || !window.jspdf) return;
  exportArea.classList.add("exporting");
  await waitForImages(exportArea);
  await waitForLayout();
  const canvas = await window.html2canvas(exportArea, {
    backgroundColor: "#ffffff",
    scale: 1.8,
    useCORS: true,
    allowTaint: true,
  });
  exportArea.classList.remove("exporting");
  const imgData = canvas.toDataURL("image/jpeg", 0.82);
  const { jsPDF } = window.jspdf;
  const pdf = new jsPDF({
    orientation: "landscape",
    unit: "pt",
    format: "a4",
  });
  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();
  const ratio = Math.min(pageWidth / canvas.width, pageHeight / canvas.height);
  const imgWidth = canvas.width * ratio;
  const imgHeight = canvas.height * ratio;
  const x = (pageWidth - imgWidth) / 2;
  const y = (pageHeight - imgHeight) / 2;
  pdf.addImage(imgData, "PNG", x, y, imgWidth, imgHeight);
  pdf.save("timeline-pola-tanam.pdf");
}

if (exportImageBtn) {
  exportImageBtn.addEventListener("click", exportTimelineImage);
}

if (exportPdfBtn) {
  exportPdfBtn.addEventListener("click", exportTimelinePdf);
}

function waitForImages(container) {
  const images = Array.from(container.querySelectorAll("img"));
  if (images.length === 0) return Promise.resolve();
  return Promise.all(
    images.map(
      (img) =>
        new Promise((resolve) => {
          if (img.complete) return resolve();
          img.onload = () => resolve();
          img.onerror = () => resolve();
        })
    )
  );
}

function waitForLayout() {
  return new Promise((resolve) => {
    requestAnimationFrame(() => {
      setTimeout(resolve, 120);
    });
  });
}

const jenisSelect = document.querySelector("select[name='jenis']");
const fieldQtyPemberian = document.querySelector(".field-qty-pemberian");
const fieldQtyBenih = document.querySelector(".field-qty-benih");
const fieldKodeBibit = document.querySelector(".field-kode-bibit");
const fieldNoDistribusi = document.querySelector(".field-no-distribusi");
const fieldEstimasi = document.querySelector(".field-estimasi");
const fieldRealisasi = document.querySelector(".field-realisasi");

function toggleFields() {
  if (!jenisSelect) return;
  const jenis = jenisSelect.value;
  const showBenih = jenis === "tanam_benih";
  const showPanen = jenis === "panen";

  if (fieldQtyPemberian) fieldQtyPemberian.classList.toggle("field-hidden", !showBenih);
  if (fieldQtyBenih) fieldQtyBenih.classList.toggle("field-hidden", !showBenih);
  if (fieldKodeBibit) fieldKodeBibit.classList.toggle("field-hidden", !showBenih);
  if (fieldNoDistribusi) fieldNoDistribusi.classList.toggle("field-hidden", !showBenih);
  if (fieldEstimasi) fieldEstimasi.classList.toggle("field-hidden", !showPanen);
  if (fieldRealisasi) fieldRealisasi.classList.toggle("field-hidden", !showPanen);
}

if (jenisSelect) {
  jenisSelect.addEventListener("change", toggleFields);
  toggleFields();
}
