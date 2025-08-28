/** @type {import('tailwindcss').Config} */
module.exports = {
  // NOTE: Update this to include the paths to all files that contain Nativewind classes.
  content: ["./App.tsx", "./src/**/*.{js,jsx,ts,tsx}"],
  presets: [require("nativewind/preset")],
  theme: {
    extend: {
      colors: {
        bgColor1: 'rgb(249, 249, 252)',
        greenColor: 'rgb(37, 165, 120)',
        darkgreenColor: 'rgb(28, 123, 91)',
        grayColor: 'rgb(240, 240, 240)',
        darkgrayColor: 'rgb(198, 199, 198)',
      },

      boxShadow: {
        'custom': '10px 10px 30px rgba(51, 53, 46, 0.2)',
        'custom': '10px 10px 30px rgba(51, 53, 46, 0.2)',
        'red': "0 4px 6px rgba(255, 0, 0, 0.4)",
      },
    },
  },
  plugins: [],
}