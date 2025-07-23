// Sidebar controls
function openNav() {
    document.getElementById("mySidebar").style.width = "250px";
}

function closeNav() {
    document.getElementById("mySidebar").style.width = "0";
}



// Show/hide arrows on hover
function showArrows(el) {
    el.querySelectorAll('.arrow').forEach(btn => {
        btn.style.display = 'block';
    });
}

function hideArrows(el) {
    el.querySelectorAll('.arrow').forEach(btn => {
        btn.style.display = 'none';
    });
}

// Next image
function nextSlide(btn) {
    const container = btn.parentElement;
    const slides = container.querySelectorAll('.slide');
    let index = [...slides].findIndex(slide => slide.classList.contains('active'));
    
    console.log("Next Slide Clicked", { slides, index });

    if (index === -1) return;

    slides[index].classList.remove('active');
    let nextIndex = (index + 1) % slides.length;
    slides[nextIndex].classList.add('active');
}

function prevSlide(btn) {
    const container = btn.parentElement;
    const slides = container.querySelectorAll('.slide');
    let index = [...slides].findIndex(slide => slide.classList.contains('active'));
    
    console.log("Next Slide Clicked", { slides, index });

    if (index === -1) return;

    slides[index].classList.remove('active');
    let nextIndex = (index + 1) % slides.length;
    slides[nextIndex].classList.add('active');
}


function addToCart(productId, element) {
    fetch(`/add_to_cart/${productId}`).then(() => {
        element.classList.add("clicked");
        setTimeout(() => {
            element.classList.remove("clicked");
        }, 1000);
    });
}


window.nextSlide = nextSlide;
window.prevSlide = prevSlide;

